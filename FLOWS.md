Цель. Пошаговые сценарии выполнения.

Flow A «Вечерний чек-ин»: Scheduler → ping.request → клавиатура 🙂|😐|🙁 → Router → Dedup → CheckinWriter → PetRender → Notifier.

Flow B «Экспорт»: /export → Export → CSV → Notifier.

Flow C «Удаление»: /delete_me → Delete → подтверждение.

Отказоустойчивость: идемпотентность по update/callback id; 429 → honour retry_after и троттлинг. 

Алерт-сигналы и инциденты — описаны в RUNBOOK по SRE.
