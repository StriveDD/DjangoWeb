from django.db import models

# Create your models here.
class Commodity(models.Model):
    commodityName = models.CharField(max_length = 64)
    imgUrl = models.CharField(max_length = 256)