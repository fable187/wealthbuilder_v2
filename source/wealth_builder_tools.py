import os
import plaid
from plaid.api import plaid_api
from plaid.model.products import Products
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.accounts_get_request import AccountsGetRequest
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pandas as pd
import json
from dataclasses import dataclass


class Plaid_Interface():

    def __init__(self):
        """
        initiates the plaid credentials and creates an api connection to the Plaid API
        """
        config_environment = {
            'sandbox': plaid.Environment.Sandbox,
            'development': plaid.Environment.Development,
            'production': plaid.Environment.Production

        }
        self.PLAID_CLIENT_ID = os.getenv('PLAID_CLIENT_ID')
        self.PLAID_SECRET = os.getenv('PLAID_SECRET')
        self.PLAID_ENV = os.getenv('PLAID_ENV')
        self.PLAID_PRODUCTS = os.getenv('PLAID_PRODUCTS').split(',')
        self.PLAID_COUNTRY_CODES = os.getenv('PLAID_COUNTRY_CODES').split(',')
        self.PLAID_REDIRECT_URI = os.getenv('PLAID_REDIRECT_URI', None)
        self.ACCESS_TOKEN = os.getenv('PLAID_ACCESS_TOKEN')
        self.host = config_environment[self.PLAID_ENV]

        self.configuration = plaid.Configuration(
            host=self.host,
            api_key={
                'clientId': self.PLAID_CLIENT_ID,
                'secret': self.PLAID_SECRET,
                'plaidVersion': '2020-09-14'
            }
        )

        self.api_client = plaid.ApiClient(self.configuration)
        self.client = plaid_api.PlaidApi(self.api_client)

        self.products = []
        for product in self.PLAID_PRODUCTS:
            self.products.append(Products(product))

    def format_error(self, e):
        """
        Formats the errors provided from Plaid Exceptions
        """
        response = json.loads(e.body)
        return {'error': {'status_code': e.status, 'display_message':
            response['error_message'], 'error_code': response['error_code'], 'error_type': response['error_type']}}

    def get_account_details(self):
        """
        Calls accounts_get() to retrieve all accounts and their current balances
        :return: Plaid Response
        """
        try:
            request = AccountsGetRequest(
                access_token=self.ACCESS_TOKEN
            )
            response = self.client.accounts_get(request)

            return response
        except plaid.ApiException as e:
            error_response = self.format_error(e)
            return error_response

    def get_plaid_accounts(self) -> pd.DataFrame:
        """
        retrieves all plaid connected accounts and returns
        them in a dataframe
        """
        account_list = self.get_account_details()
        acct_names = []
        acct_balances = []
        acct_ids = []
        for account in account_list['accounts']:
            acct_names.append(account['name'])
            acct_balances.append(account['balances']['available'])
            acct_ids.append(account['account_id'])

        return pd.DataFrame(zip(acct_ids, acct_names, acct_balances),
                            columns=['Account_ID', 'Account_Name', 'Balance'])

    @staticmethod
    def get_date_range(option="m", periods=1) -> list:
        """
        reads in number of periods and type of unit:
        m - month
        d - days
        Then returns a list of dates ranging from today and tracking back
        that many periods

        Example:  If today is 2022-10-01, 5 periods by month yields
        '2022-05-01' through '2022-10-01'
        """

        date_list = []
        start_date = datetime.today()
        date = start_date

        for period in range(periods):
            if option == 'd':
                date = date - relativedelta(days=1)
            else:
                date = date - relativedelta(months=1)
            date_list.append(date.date())
        return date_list

    def get_account_history(self, option='m', periods=1) -> pd.DataFrame:
        """
        :param option: str
        :param periods: int
        :description: takes months, weeks, or days as intergers and
        queries plaid api for all activity in those periods
        Example:  option = m, periods = 1 means look 1 month back
        :return: dataframe
        """

        date_range = self.get_date_range(periods=periods, option=option)
        date_query_list = []
        for date in date_range:
            if date < datetime.now().date():
                date_query_list.append(date)

        history_concat_list = []

        for date in date_query_list:
            trns_history = self.get_transactions_from_plaid(start=date, end=date + relativedelta(months=1))
            history_concat_list.append(trns_history)

        return pd.json_normalize(history_concat_list, record_path=['transactions'])

    def get_transactions_from_plaid(self, start=None, end=None):
        """
        :param start: datetime
        :param end: datetime
        :return: dictionary
        """
        if start is not None:
            options = TransactionsGetRequestOptions(count=500)
            request = TransactionsGetRequest(
                access_token=self.ACCESS_TOKEN,
                start_date=start,
                end_date=end,
                options=options
            )
            response = self.client.transactions_get(request)
            response_dict = response.to_dict()
            return response_dict


@dataclass
class Bill:
    name: str
    regex: str
    due_date: str
    merchant_name: str
    frequency: int = 1
    period: str = 'monthly'
    amount: float = 0

    def to_dict(self):
        return {'NAME': self.name,
                'REGEX': self.regex,
                'FREQUENCY': self.frequency,
                'MERCHANT_NAME': self.merchant_name,
                'PERIOD': self.period,
                'AMOUNT': self.amount,
                'DUE_DATE': self.due_date}


class Account_Analyzer():

    def __init__(self, account_history):
        self.bill_list = []
        self.account_history = account_history

    def add_recurring_bill(self, bill: Bill):
        """
        add a bill name to track.  This will update bill_names_list
        """
        self.bill_list.append(bill)

    def report_bills(self) -> dict:
        """
        :return: bill_list: list
        """
        return [bill.to_dict() for bill in self.bill_list]

    def analyze_bill_activity(self, bill: Bill):
        """
        :param bill: Bill
        :param checking_df: DataFrame
        :return: Dict - showing number of occurrences of bill across all billing periods
        """
        bill_filter_condition = self.account_history['merchant_name'].apply(lambda mn: str(mn).strip().lower()) == bill.merchant_name.strip().lower()
        bill_activity = self.account_history[bill_filter_condition].copy()
        bill_activity['date'] = pd.to_datetime(bill_activity['date'])
        bill_occurences = bill_activity.groupby(['date', 'name', 'amount'])['category_id'].count()
        bill_occurences_to_df = pd.DataFrame(bill_occurences).reset_index()
        bill_occurences_to_df.rename({'count': 'category_id'}, inplace=True)

        return bill_occurences_to_df

    def find_bills_in_period(self):
        """
        :param bills_to_check: list of Bills
        :return: all occurrences of the bills in the given periods
        """
        billing_acivity_list = []
        for bill in self.bill_list:
            billing_acivity_list.append(self.analyze_bill_activity(bill))
        return billing_acivity_list


if __name__ == "__main__":
    plaid_tool = Plaid_Interface()
    all_accounts = plaid_tool.get_plaid_accounts()
    transaction_history = plaid_tool.get_account_history(option='m', periods=1)
