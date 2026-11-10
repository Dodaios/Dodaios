"""The phone companion: paired devices, web push and the lead conversation on a phone.

The desktop shows a one-time pairing code (as a QR code); the phone redeems it
once for a revocable device token and from then on reads, types into and
approves the lead's one conversation through ``/api/mobile/app/*``. Nothing
here opens without a token. See ``docs/mobile-companion.md``.
"""
