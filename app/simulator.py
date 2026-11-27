"""Seeded synthetic payment stream. No ground-truth fraud label is generated or exposed."""

import random
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.schemas import TransactionCreate


class Simulator:
    def __init__(self, seed: int = 41):
        self.seed = seed
        self.rng = random.Random(seed)
        self.index = 0
        self.running = False
        self.scenario: Literal["routine", "burst"] = "burst"
        self.base_time = datetime(2025, 1, 15, 8, tzinfo=timezone.utc)

    def reset(self, scenario: Literal["routine", "burst"] = "burst", count: int = 36) -> list[TransactionCreate]:
        self.rng = random.Random(self.seed)
        self.index = 0
        self.running = False
        self.scenario = scenario
        return self.next_batch(count)

    def start(self) -> dict[str, int | bool | str]:
        self.running = True
        return self.status()

    def pause(self) -> dict[str, int | bool | str]:
        self.running = False
        return self.status()

    def status(self) -> dict[str, int | bool | str]:
        return {"running": self.running, "scenario": self.scenario, "generated_count": self.index, "seed": self.seed}

    def next_batch(self, count: int = 5) -> list[TransactionCreate]:
        records = []
        accounts = [f"acct_{number:03d}" for number in range(12)]
        for _ in range(count):
            index = self.index
            burst = self.scenario == "burst" and 24 <= index < 31
            sender = "acct_003" if burst else self.rng.choice(accounts)
            receiver = f"merchant_{self.rng.randrange(8):02d}" if burst else self.rng.choice(accounts)
            timestamp = self.base_time + timedelta(minutes=index * 17 if not burst else 500 + (index - 24) * 3)
            amount = round(self.rng.lognormvariate(4.0, 0.9), 2)
            if burst:
                amount = round(self.rng.uniform(4500, 12500), 2)
            currency = self.rng.choice(["USD", "EUR", "GBP"])
            receive_currency = currency if self.rng.random() > 0.12 else self.rng.choice(["USD", "EUR", "GBP"])
            sender_location = self.rng.choice(["US", "GB", "DE", "IN"])
            receiver_location = sender_location if self.rng.random() > 0.14 else self.rng.choice(["US", "GB", "DE", "IN"])
            records.append(TransactionCreate(
                transaction_id=f"sim_{self.seed}_{index:05d}", timestamp=timestamp,
                sender_id=sender, receiver_id=receiver, amount=amount, payment_currency=currency,
                received_currency=receive_currency, sender_location=sender_location,
                receiver_location=receiver_location, payment_type=self.rng.choice(["Transfer", "Card", "Wallet"]),
                description="Synthetic generated payment event", source="simulator",
            ))
            self.index += 1
        return records
