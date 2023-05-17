import time
from typing import List
import requests
from django.shortcuts import render, redirect
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import openai
import requests.adapters
from project import models


contents = {
    "sling pack": "https://waterflyshop.com/collections/sling-packs",
    "fanny pack": "https://waterflyshop.com/collections/fanny-pack",
    "backpack": "https://waterflyshop.com/collections/back-pack",
    "accessory": "https://waterflyshop.com/collections/accessories/Waterproof-Socks"
}

urlCnt: List[str] = []     # 保存搜集到了图片 url

Commodity = models.Commodity    # 数据库对象

start_time = None

# Create your views here.
def index(request):
    global start_time
    current_time = time.time()
    if start_time is None: start_time = time.time()
    elif current_time - start_time > 604800:
        # 七天后清空数据库
        Commodity.objects.all().delete()
        start_time = current_time
    return render(request, "HTML/index.html")


def show(request):
    global urlCnt
    api_key = request.POST.get("api_key")
    product_name = request.POST.get("product_name")
    consult = request.POST.get("consult")
    urlCnt.clear()

    # 先去数据库查找
    databaseContents = Commodity.objects.filter(commodityName = product_name)
    if len(databaseContents) > 0:
        for cnt in databaseContents:
            urlCnt.append(cnt.imgUrl)
    else:
        product_name_waterfly = contents.get(product_name)
        product_name_Amazon = product_name.split(' ')
        if product_name_waterfly is not None: urlCnt += searchImgInWaterfly(product_name_waterfly, product_name)
        urlCnt += searchImgInAmazon(product_name_Amazon, product_name)
    return render(request, "HTML/index.html", context = {"valid": True, "api_key": api_key, "product_name": product_name, "amount": len(urlCnt), "consult": consult})


def getIntroduce(request):
    api_key = request.POST.get("api_key")
    product_name = request.POST.get("product_name")
    amount = int(request.POST.get("amount"))
    consult = request.POST.get("consult")
    needAnalyseImg = urlCnt[:amount]
    outputCnt = analyseImg(needAnalyseImg, api_key, consult)
    return render(request, "HTML/index.html", context = {"valid": True, "search": True, "api_key": api_key, "product_name": product_name, "amount": len(urlCnt), "outputCnt": outputCnt, "consult": consult})


# 根据目标 url 获取图片
def downLoadPictureInAmazon(url, product_name):
    ans = []    # 用来存在满足条件的图片

    # 随机设置 ua
    ua = UserAgent(verify_ssl = False)

    # 访问目标地址
    headers = {
        'Accept-Language': 'zh-CN,zh-HK;q=0.9,zh;q=0.8',
        'User-Agent': ua.random,
        'Cookie': "session-id=138-8126141-3697145; i18n-prefs=USD; session-id-time=2082787201l;"
    }

    # 不要长时间保持连接
    session = requests.Session()
    session.keep_alive = False

    # 设置默认的重试次数
    requests.adapters.DEFAULT_RETRIES = 5

    # 设置 verify = False 取消 SSL 认证
    try:
        response = requests.get(url = url, timeout = 30, headers = headers, verify = False)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
    except requests.exceptions:
        print("have error")
    else:
        # 解析网址，提取目标图片相关信息，注：这里的解析方法是不固定的，可以根据实际的情况灵活使用
        allImage = soup.find_all("img", class_ = "s-image")
        for image in allImage:
            target = str(image)
            start, end = target.find("src="), target.find("srcset")
            targetImgUrl = target[start + 5:end - 2]
            ans.append(targetImgUrl)
            Commodity.objects.create(commodityName = product_name, imgUrl = targetImgUrl)   # 把数据添加到数据库中
            if len(ans) > 100: break
        response.close()
    return ans


# 根据目标 url 获取图片
def downLoadPictureInWaterfly(url, product_name):
    ans = []    # 用来存在满足条件的图片

    ua = UserAgent(verify_ssl = False)

    # 访问目标地址
    headers = {
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Connection': 'keep-alive',
        'User-Agent': ua.random,
        'Upgrade-Insecure-Requests': '1'
    }
    response = requests.get(url = url, timeout = 20, headers = headers)
    response.encoding = response.apparent_encoding
    soup = BeautifulSoup(response.text, "html.parser")

    # 解析网址，提取目标图片相关信息，注：这里的解析方法是不固定的，可以根据实际的情况灵活使用
    allImage = soup.find_all("img", class_ = "image__img")
    for image in allImage:
        target = str(image)
        if target.find("products") == -1: continue
        start, end = target.find("src="), target.find("srcset")
        targetUrl = "https:" + target[start + 5:end - 2]
        if ans.count(targetUrl) > 0: continue
        ans.append(targetUrl)
        Commodity.objects.create(commodityName = product_name, imgUrl = targetUrl)
    response.close()
    return ans


# 利用 GPT 去 Amazon 搜索图片
def searchImgInAmazon(cnt, product_name):
    # 去 Amazon 搜索
    urlFront = "https://www.amazon.com/s?k="
    urlRear = "&page=1&__mk_zh_CN=%E4%BA%9A%E9%A9%AC%E9%80%8A%E7%BD%91%E7%AB%99&ref=sr_pg_1"
    for prefix in cnt:
        urlFront += prefix + "+"
    urlFront = urlFront[:-1]
    url = urlFront + urlRear  # 根据关键字获取完整的 url

    page = 2
    allImageUrl = []
    while True:  # 获取所有分页的内容
        ll, lr, right = url.find("page="), url.find("&__mk_zh_CN="), url.find("ref=sr_pg_")
        urlFront, urlRear = url[:ll + 5], url[lr:right + 10]
        url = urlFront + str(page) + urlRear + str(page)
        page += 1
        currentImg = downLoadPictureInAmazon(url, product_name)
        time.sleep(5)
        if len(currentImg) < 20: break
        allImageUrl += currentImg
    return allImageUrl


# 利用 GPT 去 Waterfly 搜索图片
def searchImgInWaterfly(name, product_name):
    allImageUrl = downLoadPictureInWaterfly(name, product_name)
    return allImageUrl


# 利用 GPT 来分析图片
def analyseImg(cnt, open_api_key, consult):
    openai.api_key = open_api_key
    count = 1
    message = "产品介绍信息\n"
    for url in cnt:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": f"{consult}: {url}"}
            ],
            temperature=0.3,
            max_tokens=512
        )
        message += "第" + str(count) + "条介绍：\n"
        message += "图片地址：%s\n" % url
        message += "产品详细介绍: \n"
        message += "%s\n\n" % completion.choices[0].message["content"].strip()
        count += 1
    return message

# 使用 GPT 时需要启动代理