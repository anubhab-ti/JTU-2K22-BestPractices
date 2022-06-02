from rest_framework.exceptions import APIException
from rest_framework import status

class UnauthorizedUserException(APIException):
    status_code: int = status.HTTP_404_NOT_FOUND
    default_detail: str = "Not Found"
    default_code: str = "Records unavailable"