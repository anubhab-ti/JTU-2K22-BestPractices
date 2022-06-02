# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models

# Create your models here.
from django.contrib.auth.models import User


class Category(models.Model):
    name: models.CharField = models.CharField(max_length=200, null=False)


class Groups(models.Model):
    name: models.CharField = models.CharField(max_length=100, null=False)
    members: models.ManyToManyField = models.ManyToManyField(User, related_name='members', blank=True)


class Expenses(models.Model):
    description: models.CharField = models.CharField(max_length=200)
    total_amount: models.DecimalField = models.DecimalField(max_digits=10, decimal_places=2)
    group: models.ForeignKey = models.ForeignKey(Groups, null=True, on_delete=models.CASCADE)
    category: models.ForeignKey = models.ForeignKey(Category, default=1, on_delete=models.CASCADE)


class UserExpense(models.Model):
    expense: models.ForeignKey = models.ForeignKey(Expenses, default=1, on_delete=models.CASCADE, related_name="users")
    user: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE, related_name="expenses")
    amount_owed: models.DecimalField = models.DecimalField(max_digits=10, decimal_places=2)
    amount_lent: models.DecimalField = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self) -> str:
        return f"user: {self.user}, amount_owed: {self.amount_owed} amount_lent: {self.amount_lent}"
