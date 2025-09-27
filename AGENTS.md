Назначение. Короткий «паспорт ролей».
Scope. Только кто-что-делает и какие события принимает/отдаёт.

Определение «агента»: изолированный модуль со своей ответственностью и контрактом событий.

Список агентов (по 1–2 строки + I/O):

Webhook → принимает Telegram Update, валидирует, публикует tg.update.

Router → маппит /start и нажатия кнопок в доменные события.

Dedup → отсекает повторы в окне 10 мин.

CheckinWriter → пишет запись настроения.

PetRender → выбирает 1 из 3 спрайтов питомца.

Notifier → шлёт карточку пинга и ответ со спрайтом.

Scheduler → раз в сутки эмитит ping.request для нужных пользователей.

Export / Delete → экспорт CSV и полное удаление.

Словарь событий: tg.update, ping.request, checkin.save, checkin.saved, pet.render, pet.rendered, export.request, export.ready, delete.request, delete.done
