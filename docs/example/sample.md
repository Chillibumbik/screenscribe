# sample.webm

Duration 00:55, speakers: 3, screens: 4

> How to read: this is one timeline. A `Screen` heading marks the moment the picture changed; the block under it is the text read from the screen (only what the previous screen did not show), and the lines after it are what was said while that screen was visible. Times are from the start of the recording. Screen text is OCR and may contain misread characters.

## [00:00] `Screen: Проект: Личный кабинет клиента`

```text
Проект: Личный кабинет клиента
Этап 2: интеграция с CRM
Срок сдачи: 15 декабря
Бюджет этапа: 480 000 рублей
Команда: 3 разработчика, 1 аналитик
```

**[00:00] Speaker 1:** Добрый день, коллеги. Давайте посмотрим на план второго этапа. Вот здесь на слайде указаны срок сдачи и бюджет.

**[00:08] Speaker 2:** Да, вижу. Скажите, а этот срок включает тестирование?

**[00:12] Speaker 1:** Да, тестирование входит в этот срок. Денис, расскажи, пожалуйста, про архитектуру.

## [00:19] `Screen: Архитектура`

```text
Архитектура
Frontend: React + TypeScript
Backend: FastAPl, Python 3.12
База данных: PostgreSQL 16
Очередь задач: RabbitMQ
Деплой: Docker, Kubernetes
```

**[00:19] Speaker 3:** Конечно, на этом слайде наш текст. Обратите внимание на последнюю строку, деплей будет кубернейтес.

**[00:26] Speaker 2:** А почему для очереди выбрали именно это решение?

**[00:30] Speaker 3:** Оно уже используется в вашей инфраструктуре, поэтому так будет проще в поддержке.

## [00:34] `Screen: Задержка API со стороны CRM: высокий`

```text
Задержка API со стороны CRM: высокий
Нет тестового стенда: средний
Рост нагрузки в январе: низкий
```

**[00:35] Speaker 1:** Теперь о рисках. Самый серьёзный риск указан в первой строке таблицы.

**[00:40] Speaker 2:** Мы постараемся выдать доступ к тестовому стенду до конца недели.

## [00:44] `Screen: $ pytest tests/ -q`

```text
$ pytest tests/ -q
42 passed, 1 failed in 3.18s
FAILED tests/test_sync.py:test_retry - TimeoutError
```

**[00:45] Speaker 3:** И последнее. Вот результат пробона теста. Один тест падает по тайм-ауту, я исправлю это завтра.

**[00:52] Speaker 1:** Отлично. Тогда на сегодня всё. Спасибо всем.
