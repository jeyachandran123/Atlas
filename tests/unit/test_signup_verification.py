"""Sign-up codes: nothing is created until the code is right, and nothing can be guessed or flooded."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from app.signup.verification import MAX_ATTEMPTS, MAX_SENDS_PER_HOUR, SignupError, SignupVerifier

EMAIL = "new@example.com"


def run(coro):
    return asyncio.run(coro)


def verifier() -> tuple[SignupVerifier, fakeredis.aioredis.FakeRedis]:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return SignupVerifier(r, "test-secret", ttl_seconds=600, resend_after=60), r


async def started(v: SignupVerifier) -> str:
    return await v.start(email=EMAIL, full_name="New Person", password_hash="$2b$bcrypt-hash")


class TestStart:
    def test_the_code_is_six_digits(self):
        v, _ = verifier()
        code = run(started(v))
        assert len(code) == 6 and code.isdigit()

    def test_neither_the_code_nor_a_password_is_stored_as_typed(self):
        async def go():
            v, r = verifier()
            code = await started(v)
            raw = await r.get(f"signup:pending:{EMAIL}")
            return code, raw
        code, raw = run(go())
        assert code not in raw
        assert "$2b$bcrypt-hash" in raw  # only the bcrypt hash of the password


class TestVerify:
    def test_the_right_code_returns_the_sign_up(self):
        async def go():
            v, _ = verifier()
            code = await started(v)
            return await v.verify(EMAIL, code)
        pending = run(go())
        assert pending.full_name == "New Person" and pending.password_hash == "$2b$bcrypt-hash"

    def test_spaces_in_a_typed_code_are_ignored(self):
        async def go():
            v, _ = verifier()
            code = await started(v)
            return await v.verify(EMAIL, f"{code[:3]} {code[3:]}")
        assert run(go()).email == EMAIL

    def test_a_wrong_code_says_how_many_tries_are_left(self):
        async def go():
            v, _ = verifier()
            code = await started(v)
            wrong = "000000" if code != "000000" else "111111"
            await v.verify(EMAIL, wrong)
        with pytest.raises(SignupError) as e:
            run(go())
        assert e.value.status == 400 and f"{MAX_ATTEMPTS - 1} tries left" in e.value.message

    def test_too_many_wrong_codes_end_the_sign_up(self):
        async def go():
            v, _ = verifier()
            code = await started(v)
            wrong = "000000" if code != "000000" else "111111"
            last = None
            for _ in range(MAX_ATTEMPTS):
                try:
                    await v.verify(EMAIL, wrong)
                except SignupError as err:
                    last = err
            # Even the right code no longer works: the sign-up is gone.
            try:
                await v.verify(EMAIL, code)
            except SignupError as err:
                return last, err
            return last, None
        last, after = run(go())
        assert last.status == 429
        assert after is not None and after.status == 410

    def test_an_expired_sign_up_cannot_be_verified(self):
        v, _ = verifier()
        with pytest.raises(SignupError) as e:
            run(v.verify(EMAIL, "123456"))
        assert e.value.status == 410

    def test_complete_spends_the_code(self):
        async def go():
            v, _ = verifier()
            code = await started(v)
            await v.verify(EMAIL, code)
            await v.complete(EMAIL)
            await v.verify(EMAIL, code)
        with pytest.raises(SignupError) as e:
            run(go())
        assert e.value.status == 410


class TestResend:
    def test_a_new_code_cannot_be_asked_for_straight_away(self):
        async def go():
            v, _ = verifier()
            await started(v)
            await v.resend(EMAIL)
        with pytest.raises(SignupError) as e:
            run(go())
        assert e.value.status == 429 and e.value.retry_after and e.value.retry_after <= 60

    def test_after_the_cooldown_the_old_code_stops_working(self):
        async def go():
            v, r = verifier()
            old = await started(v)
            await r.delete(f"signup:cooldown:{EMAIL}")  # the minute has passed
            new, name = await v.resend(EMAIL)
            assert name == "New Person"
            if new != old:
                with pytest.raises(SignupError):
                    await v.verify(EMAIL, old)
            return await v.verify(EMAIL, new)
        assert run(go()).email == EMAIL

    def test_codes_per_hour_are_capped(self):
        async def go():
            v, r = verifier()
            for _ in range(MAX_SENDS_PER_HOUR):
                await started(v)
                await r.delete(f"signup:cooldown:{EMAIL}")
            await started(v)
        with pytest.raises(SignupError) as e:
            run(go())
        assert e.value.status == 429

    def test_resending_for_no_sign_up_says_it_expired(self):
        v, _ = verifier()
        with pytest.raises(SignupError) as e:
            run(v.resend(EMAIL))
        assert e.value.status == 410
