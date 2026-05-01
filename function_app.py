import azure.functions as func
import logging
from scraper import main_logic # Or just paste the scraper code here

app = func.FunctionApp()

@app.timer_trigger(schedule="0 0 * * *", arg_name="myTimer", run_on_startup=False)
def timer_trigger(myTimer: func.TimerRequest) -> None:
    if myTimer.past_due:
        logging.info('The timer is past due!')
    
    # Call your scraper logic here
    main_logic()
    logging.info('Udaipur Scraper executed successfully.')