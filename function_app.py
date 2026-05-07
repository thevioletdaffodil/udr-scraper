import azure.functions as func
import logging
from scraper import main_logic

app = func.FunctionApp()

@app.timer_trigger(
    schedule="0 0 */6 * * *",   # every 6 hours  (was midnight-only; change as needed)
    arg_name="myTimer",
    run_on_startup=False,        # set True only for local testing — avoid cold-start loops in prod
)
def timer_trigger(myTimer: func.TimerRequest) -> None:
    if myTimer.past_due:
        logging.warning("Timer is past due — running anyway.")

    logging.info("Udaipur scraper triggered.")
    try:
        main_logic()
        logging.info("Udaipur scraper finished successfully.")
    except Exception as exc:
        logging.exception("Scraper raised an unhandled exception: %s", exc)
        raise   # re-raise so Azure marks the execution as failed
