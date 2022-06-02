# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from decimal import Decimal
from time import time
import urllib.request
from datetime import datetime

from django.http import HttpResponse
from django.contrib.auth.models import User

# Create your views here.
from rest_framework.permissions import AllowAny
from rest_framework.decorators import api_view, action, authentication_classes, permission_classes
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework import status

from restapi.serializers import Expenses, UserSerializer, Category, CategorySerializer, Groups, GroupSerializer, ExpensesSerializer, UserExpense
from restapi.custom_exception import UnauthorizedUserException
from django.db.models.query import QuerySet

import constants
import concurrent.futures
import logging

logger = logging.getLogger(__name__)

def index(_request) -> HttpResponse:
    return HttpResponse("Hello, world. You're at Rest.")

@api_view(['POST'])
def logout(request) -> Response:
    '''
    Logs out the user identified by auth_token in request
    '''
    request.user.auth_token.delete()
    logger.info(f'Logged out user with auth_token: {request.user.auth_token}')
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
def balance(request) -> Response:
    '''
    Returns the set of expenses related to the account of the user
    '''
    user = request.user
    expenses = Expenses.objects.filter(users__in=user.expenses.all())
    final_balance: dict = {}
    for expense in expenses:
        expense_balances = normalize(expense)
        for eb in expense_balances:
            from_user = eb['from_user']
            to_user = eb['to_user']
            if from_user == user.id:
                final_balance[to_user] = final_balance.get(
                    to_user, 0) - eb['amount']
            if to_user == user.id:
                final_balance[from_user] = final_balance.get(
                    from_user, 0) + eb['amount']
    final_balance: dict = {k: v for k, v in final_balance.items() if v != 0}

    response: list[dict] = [
        {"user": k, "amount": int(v)} for k, v in final_balance.items()]
    return Response(response, status=status.HTTP_200_OK)


def normalize(expense) -> list[dict]:
    '''
    Returns the balanced expense for the passed expense

    Parameters:
    expense: An expense made from or to a user's account
    '''
    user_balances = expense.users.all()
    # not giving a static type to dues
    # first initialised (and used in line 60) as a dict, but then reassigned a list[tuple] in line 63
    dues = {}
    for user_balance in user_balances:
        dues[user_balance.user] = dues.get(user_balance.user, 0) + user_balance.amount_lent \
            - user_balance.amount_owed
    dues = [(k, v) for k, v in sorted(dues.items(), key=lambda item: item[1])]
    start: int = 0
    end: int = len(dues) - 1
    balances: list[dict] = []
    while start < end:
        amount: int = min(abs(dues[start][1]), abs(dues[end][1]))
        user_balance: dict = {
            "from_user": dues[start][0].id, "to_user": dues[end][0].id, "amount": amount}
        balances.append(user_balance)
        dues[start] = (dues[start][0], dues[start][1] + amount)
        dues[end] = (dues[end][0], dues[end][1] - amount)
        if dues[start][1] == 0:
            start += 1
        else:
            end -= 1
    return balances


class UserViewSet(ModelViewSet):
    queryset: QuerySet = User.objects.all()
    serializer_class: type = UserSerializer
    permission_classes: tuple[type] = (AllowAny,)


class CategoryViewSet(ModelViewSet):
    queryset: QuerySet = Category.objects.all()
    serializer_class: type = CategorySerializer
    http_method_names: list[str] = ['get', 'post']


class GroupViewSet(ModelViewSet):
    queryset: QuerySet = Groups.objects.all()
    serializer_class: type = GroupSerializer

    def get_queryset(self):
        '''
        Returns the query set of groups for a given user
        '''
        user = self.request.user
        groups = user.members.all()
        if self.request.query_params.get('q', None) is not None:
            groups = groups.filter(
                name__icontains=self.request.query_params.get('q', None))
        return groups

    def create(self, request, *args, **kwargs) -> Response:
        '''
        Creates a group for a user with given data
        '''
        user = self.request.user
        data = self.request.data
        group: Groups = Groups(**data)
        group.save()
        group.members.add(user)
        serializer = self.get_serializer(group)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(methods=['put'], detail=True)
    def members(self, request, pk=None) -> Response:
        '''
        Adds or removes users to a group
        '''
        group = Groups.objects.get(id=pk)
        if group not in self.get_queryset():
            logger.error(f'Attempt to add or remove members to group with primary key: {pk} by unauthorised user')
            raise UnauthorizedUserException()
        body = request.data
        if body.get('add', None) is not None and body['add'].get('user_ids', None) is not None:
            added_ids = body['add']['user_ids']
            for user_id in added_ids:
                group.members.add(user_id)
        if body.get('remove', None) is not None and body['remove'].get('user_ids', None) is not None:
            removed_ids = body['remove']['user_ids']
            for user_id in removed_ids:
                group.members.remove(user_id)
        group.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=['get'], detail=True)
    def expenses(self, _request, pk=None) -> Response:
        '''
        Returns the list of expenses made by a group
        '''
        group = Groups.objects.get(id=pk)
        if group not in self.get_queryset():
            logger.error(f'Attempt to retrieve expenses of group with primary key: {pk} by unauthorised user')
            raise UnauthorizedUserException()
        expenses = group.expenses_set
        serializer: ExpensesSerializer = ExpensesSerializer(
            expenses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(methods=['get'], detail=True)
    def balances(self, _request, pk=None) -> Response:
        '''
        Returns the balances of a group
        '''
        group = Groups.objects.get(id=pk)
        if group not in self.get_queryset():
            logger.error(f'Attempt to retrieve balances of group with primary key: {pk} by unauthorised user')
            raise UnauthorizedUserException()
        expenses = Expenses.objects.filter(group=group)
        dues = {}
        for expense in expenses:
            user_balances = UserExpense.objects.filter(expense=expense)
            for user_balance in user_balances:
                dues[user_balance.user] = dues.get(user_balance.user, 0) + user_balance.amount_lent \
                    - user_balance.amount_owed
        dues = [(k, v)
                for k, v in sorted(dues.items(), key=lambda item: item[1])]
        start: int = 0
        end: int = len(dues) - 1
        balances: list[dict] = []
        while start < end:
            amount = min(abs(dues[start][1]), abs(dues[end][1]))
            amount = Decimal(amount).quantize(Decimal(10)**-2)
            user_balance: dict = {
                "from_user": dues[start][0].id, "to_user": dues[end][0].id, "amount": str(amount)}
            balances.append(user_balance)
            dues[start] = (dues[start][0], dues[start][1] + amount)
            dues[end] = (dues[end][0], dues[end][1] - amount)
            if dues[start][1] == 0:
                start += 1
            else:
                end -= 1

        return Response(balances, status=status.HTTP_200_OK)


class ExpensesViewSet(ModelViewSet):
    queryset: QuerySet = Expenses.objects.all()
    serializer_class: type = ExpensesSerializer

    def get_queryset(self):
        '''
        Returns the query set for given user
        '''
        user = self.request.user
        if self.request.query_params.get('q', None) is not None:
            expenses = Expenses.objects.filter(users__in=user.expenses.all())\
                .filter(description__icontains=self.request.query_params.get('q', None))
        else:
            expenses = Expenses.objects.filter(users__in=user.expenses.all())
        return expenses


@api_view(['post'])
@authentication_classes([])
@permission_classes([])
def log_processor(request) -> Response:
    '''
    Returns a cleaned and timestamp sorted list of logs for given request data
    '''
    data = request.data
    num_threads = data['parallelFileProcessingCount']
    log_files = data['logFiles']
    if num_threads <= 0 or num_threads > 30:
        logger.info(f'Failed to process logs for request: {data} as given number of threads: {num_threads} is outside the expected bounds [1, 30]')
        return Response({"status": "failure", "reason": "Parallel Processing Count out of expected bounds"},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(log_files) == 0:
        logger.info(f'Failed to process logs for request: {data} as no log files are provided in request')
        return Response({"status": "failure", "reason": "No log files provided in request"},
                        status=status.HTTP_400_BAD_REQUEST)
    logs: multi_threaded_reader = multi_threaded_reader(
        urls=data['logFiles'], num_threads=data['parallelFileProcessingCount'])
    sorted_logs: list = sort_by_time_stamp(logs)
    cleaned: list = transform(sorted_logs)
    data: dict = aggregate(cleaned)
    response: list = response_format(data)
    return Response({"response": response}, status=status.HTTP_200_OK)


def sort_by_time_stamp(logs):
    '''
    Returns a list of logs sorted by timestamp
    '''
    data: list = []
    for log in logs:
        data.append(log.split(" "))
    data = sorted(data, key=lambda elem: elem[1])
    return data


def response_format(raw_data) -> list:
    '''
    Returns a list of logs formatted for the response object
    '''
    response: list = []
    for timestamp, data in raw_data.items():
        entry: dict = {'timestamp': timestamp}
        logs: list[dict] = []
        data: dict = {k: data[k] for k in sorted(data.keys())}
        for exception, count in data.items():
            logs.append({'exception': exception, 'count': count})
        entry['logs'] = logs
        response.append(entry)
    return response


def aggregate(cleaned_logs) -> dict:
    '''
    Returns an aggregated dictionary of logs from cleaned logs
    '''
    data: dict = {}
    for log in cleaned_logs:
        [key, text] = log
        value = data.get(key, {})
        value[text] = value.get(text, 0)+1
        data[key] = value
    return data


def transform(logs) -> list:
    '''
    Returns a list of logs transformed into a valid format for the response object
    '''
    result: list = []
    for log in logs:
        [_, timestamp, text] = log
        text = text.rstrip()
        timestamp: datetime = datetime.utcfromtimestamp(
            int(int(timestamp)/1000))
        hours, minutes = timestamp.hour, timestamp.minute
        key = ''

        if minutes >= 45:
            if hours == 23:
                key = "{:02d}:45-00:00".format(hours)
            else:
                key = "{:02d}:45-{:02d}:00".format(hours, hours+1)
        elif minutes >= 30:
            key = "{:02d}:30-{:02d}:45".format(hours, hours)
        elif minutes >= 15:
            key = "{:02d}:15-{:02d}:30".format(hours, hours)
        else:
            key = "{:02d}:00-{:02d}:15".format(hours, hours)

        result.append([key, text])
        print(key)

    return result


def reader(url, timeout):
    '''
    Makes a request to the passed url and returns the read data
    '''
    with urllib.request.urlopen(url, timeout=timeout) as conn:
        return conn.read()


def multi_threaded_reader(urls, num_threads) -> list:
    """
        Read multiple files through HTTP
    """
    result: list = []
    start_time = int(time.time() * 1000.0)
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        future_url_map = {executor.submit(
            reader, url, constants.MULTI_THREADED_READER_TIMEOUT): url for url in urls}
        for future in concurrent.futures.as_completed(future_url_map):
            url = future_url_map[future]
            try:
                data = future.result()
                data = data.decode('utf-8')
                result.extend(data.split('\n'))
            except Exception as e:
                logger.error(f"Concurrent execution of multithreaded reader with number of urls: {len(urls)} and number of threads: {num_threads} failed for url: {url} due to {e}")
                pass
    end_time = int(time.time() * 1000.0)
    logger.info(f"Multithreaded reader executed succesfully with {len(urls)} urls and {num_threads} threads in {end_time - start_time} ms")
    result = sorted(result, key=lambda elem: elem[1])
    return result
