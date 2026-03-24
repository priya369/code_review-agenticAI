from datetime import datetime
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.dummy import DummyOperator  # deprecated operator
from airflow.models import Variable

# ❌ CRITICAL: Top-level code execution (API call at import time)
response = requests.get("https://api.example.com/config")
CONFIG = response.json()

# ❌ CRITICAL: Hard-coded credentials
DB_PASSWORD = "supersecret123"
API_TOKEN = "sk-prod-abc123xyz"

# ❌ CRITICAL: Dynamic start_date
dag = DAG(
    dag_id="etl_user_data",           # ❌ doesn't match file name
    start_date=datetime.now(),         # ❌ CRITICAL: dynamic start_date
    # catchup not set                  # ❌ CRITICAL: missing catchup
    # schedule not set                 # ❌ CRITICAL: missing schedule
    max_active_runs=3,
    default_args={
        "owner": "airflow",
        # ❌ WARNING: no retries defined
        # ❌ WARNING: no retry_delay defined
        # ❌ WARNING: no on_failure_callback
    },
    # ❌ INFO: no tags
)


def fetch_users():
    """Fetch users from the API."""
    try:
        # ❌ WARNING: uses hard-coded token from module level
        headers = {"Authorization": f"Bearer {API_TOKEN}"}
        r = requests.get("https://api.example.com/users", headers=headers)
        return r.json()
    except:                             # ❌ WARNING: bare except clause
        print("something went wrong")
        return []


def process_users(**kwargs):
    users = fetch_users()
    # No idempotency — blindly inserts every run
    for user in users:
        print(f"Processing {user}")
        # imagine a DB insert here with no upsert logic  # ❌ INFO: not idempotent


def send_report(**kwargs):
    import smtplib
    # ❌ CRITICAL: hard-coded credentials inside function
    smtp_pass = "email_password_plain"
    print(f"Sending report with password: {smtp_pass}")


# ❌ WARNING: deprecated DummyOperator
start = DummyOperator(task_id="start", dag=dag)

fetch_task = PythonOperator(
    task_id="fetch_users",
    python_callable=fetch_users,
    dag=dag,
    # ❌ WARNING: no execution_timeout
)

process_task = PythonOperator(
    task_id="process_users",
    python_callable=process_users,
    provide_context=True,              # ❌ WARNING: deprecated provide_context
    dag=dag,
)

report_task = PythonOperator(
    task_id="send_report",
    python_callable=send_report,
    provide_context=True,
    dag=dag,
)

# ❌ WARNING: deprecated DummyOperator
end = DummyOperator(task_id="end", dag=dag)

start >> fetch_task >> process_task >> report_task >> end
