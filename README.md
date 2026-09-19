# Обробка повідомлень Telegram за допомогою LLM

Цей проєкт виділяє структуровані спостереження з Telegram повідомлень з метою
подальшого аналізу того, як соціальні групи представлені в соціальних медіа.

Цей проєкт є проміжним етапом загальної задачі:

```text
збір повідомлень Telegram
  -> підготовка структурованих спостережень
  -> агрегація за групою, каналом і часом
  -> побудова аналітичного соціального портрета
```

Проєкт містить скрипти для підготовки тестового набору даних,
фільтрації нерелевантних повідомлень, обробки повідомлень за допомогою LLM,
перегляду результатів локальному веб-інтерфейсі, розрахунок використання токенів.

Веб-інтерфейс дозволяє переглянути оригінальні повідомлення Telegram поруч зі
 результатом обробки LLM, підтримує фільтрацію за суб’єктом повідомлення.

![Вебінтерфейс для аналізу Telegram](figs/web-example.jpeg)

## Використання

Команди мають бути виконані з кореневої директорії проєкту. Python і необхідні залежності
мають бути доступні в активному середовищі. Для обробки за допомогою LLM також
потрібна змінна середовища `OPENAI_API_KEY`.

<details>
<summary><code>scripts/collect_test_dataset.py</code> — створення тестової вибірки</summary>

Створює тестової вибірку зі 100 повідомлень з історичного CSV-файлу:

```bash
python scripts/collect_test_dataset.py \
  --historic_file=/path/to/source.csv \
  --n=100 \
  --output=data/test/dataset.csv
```

Скрипт зберігає всі стовпці CSV. Сід фіксований, тому повторні запуски з тим самим джерелом
створюють однакову вибірку.

</details>

<details>
<summary><code>scripts/filter_irrelevant_messages.py</code> — видалення нерелевантних повідомлень</summary>

Фільтрує тестовий набір даних і, за потреби, зберігає відхилені рядки
разом із причинами їх відхилення:

```bash
python scripts/filter_irrelevant_messages.py \
  --input_file=data/test/dataset.csv \
  --output_file=data/test/relevant.csv \
  --rejected_file=data/test/rejected.csv
```

Фільтр видаляє такі повідомлення, як короткі або порожні дописи, оперативні
оновлення про повітряні тривоги, очевидну рекламу та графіки комунальних
відключень.

</details>

<details>
<summary><code>scripts/process_messages.py</code> — обробка повідомлень через LLM</summary>

Обробка повідомлень асинхронно через OpenAI API:

```bash
python scripts/process_messages.py process \
  --input_file=data/test/relevant.csv \
  --output_file=data/test/results.jsonl \
  --prompt_folder=prompts/v3
```
Кожен запис JSONL містить ID повідомлення з указанням джерела, структурований
результат, версію prompt, метадані моделі та відповіді, а також дані про
використання токенів.

Робота через Batch API:

```bash
python scripts/process_messages.py submit_batch \
  --input_file=data/test/relevant.csv \
  --prompt_folder=prompts/v3
```

Після завершення batch зберіть його результати:

```bash
python scripts/process_messages.py collect_batch \
  --batch_id=BATCH_ID \
  --output_file=data/test/results.jsonl \
  --prompt_folder=prompts/v3
```


</details>

<details>
<summary><code>scripts/visualize_results.py</code> — перегляд результатів у браузері</summary>

Запустити локальний вебі-нтерфейс:

```bash
python scripts/visualize_results.py \
  --input_file=data/test/relevant.csv \
  --results_file=data/test/results.jsonl
```

Відкрийте URL, який виведе скрипт.

</details>

<details>
<summary><code>scripts/count_token_usage.py</code> — використання токенів та розрахунок вартості</summary>

Вивести підсумок використання токенів:

```bash
python scripts/count_token_usage.py \
  --input_file=data/test/results.jsonl
```

Оцінка вартість, передавши ціни за мільйон токенів для звичайних вхідних,
кешованих вхідних і вихідних токенів у зазначеному порядку:

```bash
python scripts/count_token_usage.py \
  --input_file=data/test/results.jsonl \
  --token_prices='[0.2,0.02,1.2]'
```
