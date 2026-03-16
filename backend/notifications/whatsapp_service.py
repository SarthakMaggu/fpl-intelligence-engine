"""
Pre-deadline WhatsApp alert via Twilio.

Sent 6 hours before GW deadline (scheduled via APScheduler).
Only active if TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_WHATSAPP,
and NOTIFICATION_WHATSAPP_TO are all set.
"""
import asyncio
from functools import partial
from loguru import logger


class WhatsAppService:
    def __init__(self):
        from core.config import settings
        self.settings = settings

        if not settings.whatsapp_enabled:
            raise RuntimeError("WhatsApp not configured (missing Twilio credentials)")

        from twilio.rest import Client
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    async def send_deadline_alert(self, gw_data: dict) -> bool:
        """Send pre-deadline WhatsApp alert."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, partial(self._send_sync, gw_data)
        )
        return result

    def _send_sync(self, gw_data: dict) -> bool:
        """Sync Twilio send (run in executor)."""
        try:
            message_body = self._build_message(gw_data)

            from_number = self.settings.TWILIO_WHATSAPP_FROM
            to_number = self.settings.TWILIO_WHATSAPP_TO
            message = self.client.messages.create(
                body=message_body,
                from_=f"whatsapp:{from_number}" if not from_number.startswith("whatsapp:") else from_number,
                to=f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number,
            )

            logger.info(f"WhatsApp alert sent: {message.sid}")
            return True

        except Exception as e:
            logger.error(f"WhatsApp send failed: {e}")
            return False

    def _build_message(self, gw_data: dict) -> str:
        """Build the pre-deadline WhatsApp message text."""
        gw = gw_data.get("gameweek", "?")
        deadline = gw_data.get("deadline", "soon")

        lines = [f"⚽ *FPL Intelligence — GW{gw} Deadline in 6h*"]
        lines.append(f"Deadline: {deadline}")
        lines.append("")

        # Captain
        cap = gw_data.get("captain_recommendation")
        if cap:
            lines.append(f"👑 Captain: *{cap.get('web_name','?')}* (FDR {cap.get('fdr_next','?')})")

        # Injuries
        injuries = gw_data.get("injury_alerts", [])
        if injuries:
            lines.append("")
            lines.append("🏥 Injury alerts:")
            for inj in injuries[:3]:
                chance = inj.get("chance_of_playing")
                chance_str = f" ({chance}%)" if chance is not None else ""
                lines.append(f"  • {inj['web_name']}{chance_str}")

        # Suspension risk
        suspensions = gw_data.get("suspension_risk", [])
        if suspensions:
            lines.append("")
            lines.append("🟨 Suspension risk:")
            for sus in suspensions[:2]:
                lines.append(f"  • {sus['web_name']} ({sus.get('yellow_cards',0)} yellows)")

        # Blank GW
        blanks = gw_data.get("blank_gw_starters", [])
        if blanks:
            lines.append("")
            names = ", ".join(b["web_name"] for b in blanks[:3])
            lines.append(f"❌ Blank starters: {names}")

        # Double GW
        doubles = gw_data.get("double_gw_players", [])
        if doubles:
            lines.append("")
            names = ", ".join(d["web_name"] for d in doubles[:3])
            lines.append(f"✅ Double GW: {names}")

        lines.append("")
        lines.append("_FPL Intelligence Engine_")

        return "\n".join(lines)
