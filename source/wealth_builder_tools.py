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
        response = json.loads(e.body)
        return {'error': {'status_code': e.status, 'display_message':
            response['error_message'], 'error_code': response['error_code'], 'error_type': response['error_type']}}

    def get_account_details(self):
        try:
            request = AccountsGetRequest(
                access_token=self.ACCESS_TOKEN
            )
            response = self.client.accounts_get(request)

            return response
        except plaid.ApiException as e:
            error_response = self.format_error(e)
            return error_response

    def get_plaid_accounts(self):
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
    def get_date_range(option="m", periods=1):
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

    def get_account_history(self, option='m', periods=1):

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
    due_date = int # verify this field is appearing.. was having issues..
    frequency: int = 1
    period: str = 'monthly'
    amount: float = 0


    def to_dict(self):
        return {'NAME': self.name,
                'FREQUENCY': self.frequency,
                'PERIOD': self.period,
                'AMOUNT': self.amount,
                'DUE_DATE': self.due_date}

class Account_Analyzer():

    def __init__(self):
        self.bill_list = []

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

    def find_bills_in_period(self, bills_to_check: list):
        """
        :param bills_to_check: list of Bills
        :return: all occurrences of the bills in the given periods
        """


if __name__ == "__main__":
    plaid_tool = Plaid_Interface()
    all_accounts = plaid_tool.get_plaid_accounts()
    transaction_history = plaid_tool.get_account_history(option='m', periods=1)
