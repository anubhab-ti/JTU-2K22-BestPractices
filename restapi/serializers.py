from rest_framework.serializers import ModelSerializer
from rest_framework.serializers import ValidationError
from django.contrib.auth.models import User

from restapi.models import Category, Groups, UserExpense, Expenses


class UserSerializer(ModelSerializer):
    def create(self, validated_data) -> User:
        '''
        Creates an user for given validated data and returns the user object
        '''
        user: User = User.objects.create_user(**validated_data)
        return user

    class Meta(object):
        model: type = User
        fields: tuple[str, str, str] = ('id', 'username', 'password')
        extra_kwargs: dict = {
            'password': {'write_only': True}
        }


class CategorySerializer(ModelSerializer):
    class Meta(object):
        model: type = Category
        fields: str = '__all__'


class GroupSerializer(ModelSerializer):
    members: UserSerializer = UserSerializer(many=True, required=False)

    class Meta(object):
        model: type = Groups
        fields: str = '__all__'


class UserExpenseSerializer(ModelSerializer):
    class Meta(object):
        model: type = UserExpense
        fields: list[str] = ['user', 'amount_owed', 'amount_lent']


class ExpensesSerializer(ModelSerializer):
    users: UserExpenseSerializer = UserExpenseSerializer(
        many=True, required=True)

    def create(self, validated_data):
        '''
        Creates an expense for given users and validated data and returns the expense object
        '''
        expense_users = validated_data.pop('users')
        expense = Expenses.objects.create(**validated_data)
        for eu in expense_users:
            UserExpense.objects.create(expense=expense, **eu)
        return expense

    def update(self, instance, validated_data):
        '''
        Updates the data for expenses from given validated data
        '''
        user_expenses = validated_data.pop('users')
        instance.description = validated_data['description']
        instance.category = validated_data['category']
        instance.group = validated_data.get('group', None)
        instance.total_amount = validated_data['total_amount']

        if user_expenses:
            instance.users.all().delete()
            UserExpense.objects.bulk_create(
                [
                    user_expense(expense=instance, **user_expense)
                    for user_expense in user_expenses
                ],
            )
        instance.save()
        return instance

    def validate(self, attrs):
        '''
        Validates that the same user does not appear multiple times in the data
        '''
        user_ids = [user['user'].id for user in attrs['users']]
        if len(set(user_ids)) != len(user_ids):
            raise ValidationError('Single user appears multiple times')

        return attrs

    class Meta(object):
        model: type = Expenses
        fields: str = '__all__'
