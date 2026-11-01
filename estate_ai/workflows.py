import asyncio
import logging

from pymongo.errors import DuplicateKeyError

from estate_ai.agent import EstateAgent
from estate_ai.db import Audit, Customer, Job, Message, Outbox, now
from estate_ai.document_query import select
from estate_ai.messaging import WhatsAppClient
from estate_ai.tools import ToolService, confirm_proposal

log = logging.getLogger(__name__)
STOP_WORDS = {"stop", "unsubscribe", "opt out", "stop messaging me", "बंद करो", "ਬੰਦ ਕਰੋ"}
HUMAN_WORDS = {"human", "agent", "dealer", "talk to a human", "talk to dealer"}


def enqueue(factory, event_id: str, phone: str, text: str, channel: str, timestamp: float | None = None):
    with factory() as session:
        if session.get(Job, event_id):
            return False
        customer = session.get(Customer, phone)
        if customer is None:
            customer = Customer(phone=phone)
            session.add(customer)
            session.flush()
        received = min(timestamp if timestamp is not None else now(), now())
        customer.last_inbound = max(customer.last_inbound, received)
        command = text.strip().casefold().rstrip(".!।")
        if command in STOP_WORDS:
            customer.opted_out = True
            customer.paused = True
            session.add(Audit(phone=phone, action="opt_out", detail=event_id))
        elif command in HUMAN_WORDS:
            customer.paused = True
            session.add(Audit(phone=phone, action="dealer_alert", detail="Buyer requested human takeover"))
        session.add(Message(id=event_id, phone=phone, role="user", content=text))
        session.add(
            Job(
                id=event_id,
                phone=phone,
                text=text,
                channel=channel,
                state="suppressed" if customer.paused or customer.opted_out else "pending",
            )
        )
        try:
            session.commit()
        except DuplicateKeyError:
            session.rollback()
            return False
        return True


class Worker:
    """Durable MongoDB inbox/outbox with one leased worker across revisions."""

    def __init__(self, factory, settings, agent=None, whatsapp=None):
        self.factory = factory
        self.settings = settings
        self.agent = agent or EstateAgent(settings)
        self.whatsapp = whatsapp or WhatsAppClient(settings)
        self.lock = asyncio.Lock()

    def recover(self):
        with self.factory() as session:
            for job in session.scalars(select(Job).where(Job.state == "processing")):
                job.state = "pending"
            for outgoing in session.scalars(select(Outbox).where(Outbox.state == "sending")):
                outgoing.state = "delivery_unknown"
                outgoing.error = "Interrupted send; inspect before retrying"
            session.commit()

    async def tick(self):
        async with self.lock:
            await self.process_one()
            await self.send_one()

    async def process_one(self):
        with self.factory() as session:
            job = session.scalar(select(Job).where(Job.state == "pending").order_by(Job.created).limit(1))
            if not job or job.next_attempt > now():
                return
            customer = session.get(Customer, job.phone)
            if customer.paused or customer.opted_out:
                job.state = "suppressed"
                session.commit()
                return
            job.state = "processing"
            job.attempts += 1
            job_id, phone = job.id, job.phone
            session.commit()
            try:
                if job.id.startswith("browse:"):
                    reply = ToolService(
                        session, phone, job.id, self.settings.allow_demo_data
                    ).browse_properties()
                elif job.id.startswith("more:"):
                    reply = ToolService(
                        session, phone, job.id, self.settings.allow_demo_data
                    ).more_properties()
                elif job.text.strip().casefold().startswith("confirm "):
                    reply = confirm_proposal(session, phone, job.text, job.id)
                else:
                    reply = await self.agent.reply(session, phone, job.id)
                # See takeover/opt-out changes that occurred while the model was running.
                own_pause = customer.paused
                session.refresh(customer)
                if customer.opted_out or (customer.paused and not own_pause):
                    session.rollback()
                    with self.factory() as cancelled:
                        cancelled.get(Job, job_id).state = "suppressed"
                        cancelled.commit()
                    return
                session.add(Message(id=f"reply:{job.id}", phone=phone, role="assistant", content=reply))
                session.add(Outbox(id=job.id, phone=phone, body=reply, channel=job.channel))
                job.state = "done"
                session.commit()
            except Exception as exc:  # noqa: BLE001 - Isolate failed jobs, roll back, and record bounded retries.
                session.rollback()
                job = session.get(Job, job_id)
                job.error = type(exc).__name__  # Never log tokens, contact details or provider bodies.
                if job.attempts >= 3:
                    job.state = "failed"
                    session.get(Customer, phone).paused = True
                    session.add(Audit(phone=phone, action="dealer_alert", detail="Agent processing failed"))
                else:
                    job.state = "pending"
                    job.next_attempt = now() + 2**job.attempts
                session.commit()
                log.warning("Agent job failed (%s)", type(exc).__name__)

    async def send_one(self):
        with self.factory() as session:
            item = session.scalar(
                select(Outbox).where(Outbox.state == "pending").order_by(Outbox.created).limit(1)
            )
            if not item:
                return
            customer = session.get(Customer, item.phone)
            # Even simulated messages respect opt-outs and the inbound service window.
            if customer.opted_out or customer.paused or now() - customer.last_inbound >= 86400:
                item.state = "suppressed"
                session.commit()
                return
            if item.channel == "simulate":
                item.state = "simulated"
                session.commit()
                return
            if self.settings.whatsapp_mode != "live":
                item.state = "suppressed"
                item.error = "Live WhatsApp mode disabled"
                session.commit()
                return
            item.state = "sending"
            session.commit()
            try:
                item.provider_id = await self.whatsapp.send(item.phone, item.body)
                item.state = "accepted"  # Provider accepted; not proof of delivery.
            except Exception as exc:  # noqa: BLE001 - Any transport failure can have an ambiguous side effect.
                # A timeout may mean Meta accepted the message. Never blindly resend.
                item.state = "delivery_unknown"
                item.error = type(exc).__name__
                session.add(
                    Audit(phone=item.phone, action="dealer_alert", detail="WhatsApp send needs review")
                )
            session.commit()

    async def run(self):
        while True:
            lease = self.factory.lease()
            active = None
            try:
                if not lease.acquire():
                    await asyncio.sleep(2)
                    continue
                active = asyncio.create_task(self._run_active())
                while True:
                    done, _ = await asyncio.wait({active}, timeout=15)
                    if done:
                        await active
                        break
                    if not lease.renew():
                        raise RuntimeError("Worker lease lost")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - Re-elect after sanitized database/lease failure.
                log.warning("Worker leadership interrupted (%s)", type(exc).__name__)
            finally:
                if active:
                    active.cancel()
                    await asyncio.gather(active, return_exceptions=True)
                try:
                    lease.release()
                except Exception as exc:  # noqa: BLE001 - Expiry provides recovery if release is unreachable.
                    log.warning("Worker lease release failed (%s)", type(exc).__name__)
            await asyncio.sleep(2)

    async def _run_active(self):
        self.recover()
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - Keep the worker alive with sanitized failures.
                log.warning("Worker iteration failed (%s)", type(exc).__name__)
            await asyncio.sleep(0.5)
