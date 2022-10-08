# @Time : 2022/10/2
# @Author :@Zhang Jiale @Dimlitter @6dylan6
# @File : jdspider.py

import json
import logging
import random
import re
import os
import sys
import time
from urllib.parse import quote, urlencode

import requests
import zhon.hanzi
from lxml import etree

try:
    from fake_useragent import UserAgent
except:
    print('解决依赖问题...稍等')
    os.system('pip3 install fake-useragent &> /dev/null')
    from fake_useragent import UserAgent


from Free_proxy_pool import proxy_pool
from requests.adapters import HTTPAdapter

from requests.packages.urllib3.poolmanager import PoolManager
import ssl

# Reference: https://github.com/fxsjy/jieba/blob/1e20c89b66f56c9301b0feed211733ffaa1bd72a/jieba/__init__.py#L27
log_console = logging.StreamHandler(sys.stderr)
default_logger = logging.getLogger('jdspider')
default_logger.setLevel(logging.DEBUG)
default_logger.addHandler(log_console)


class MyAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(num_pools=connections,
                                       maxsize=maxsize,
                                       block=block,
                                       ssl_version=ssl.PROTOCOL_TLSv1)


class JDSpider:
    # 爬虫实现类：传入商品类别（如手机、电脑），构造实例。然后调用getData搜集数据。
    def __init__(self, categlory, ck):

        self.UA = UserAgent(use_cache_server=False)
        self.UserAgent = []
        for i in range(20):  # 随机生成十个User-Agent
            if i % 2 == 0:
                self.UserAgent.append(self.UA.firefox)
            else:
                self.UserAgent.append(self.UA.chrome)
        self.proxy_pool = proxy_pool.Free_proxy_pool()
        self.proxy = None
        self.retryMaxCount = 20
        self.retryCount = 0
        # jD起始搜索页面
        self.startUrl = "https://so.m.jd.com/ware/search.action?keyword=%s&searchFrom=home&sf=11&as=1" % (
            quote(categlory))
        # self.startUrl = "https://search.jd.com/Search?keyword=%s&enc=utf-8" % (
        #     quote(categlory))
        self.commentBaseUrl = "https://sclub.jd.com/comment/productPageComments.action?"
        self.headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'zh-CN,zh;q=0.9',
            'cache-control': 'max-age=0',
            'dnt': '1',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="98", "Google Chrome";v="98"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': random.choice(self.UserAgent)
        }
        self.productsId = self.getId()
        self.comtype = {1: "差评", 2: "中评", 3: "好评"}
        self.categlory = categlory
        self.ck = ck
        self.iplist = {
            'http': [],
            'https': []
        }

    def getProxy(self):
        if self.proxy == None:
            self.proxy = self.proxy_pool.get_a_proxy()
        return self.proxy

    def getParamUrl(self, productid, page, score):
        params = {  # 用于控制页数，页面信息数的数据，非常重要，必不可少，要不然会被JD识别出来，爬不出相应的数据。
            "productId": "%s" % (productid),
            "score": "%s" % (score),  # 1表示差评，2表示中评，3表示好评
            "sortType": "5",
            "page": "%s" % (page),
            "pageSize": "10",
            "isShadowSku": "0",
            "rid": "0",
            "fold": "1"
        }
        url = self.commentBaseUrl + urlencode(params)
        return params, url

    def getHeaders(self, productid):  # 和初始的self.header不同，这是搜集某个商品的header，加入了商品id，我也不知道去掉了会怎样。
        header = {
            "User-Agent": random.choice(self.UserAgent),
            "Cookie": self.ck.encode("utf-8")
        }
        return header

    def getId(self):  # 获取商品id，为了得到具体商品页面的网址。结果保存在self.productId的数组里
        try:
            # 一开始的请求页面
            session = requests.Session()
            session.mount('https://', MyAdapter())
            headers = self.headers
            headers['user-agent'] = random.choice(self.UserAgent)
            # 随机获取UA和代理IP
            response = session.get(
                self.startUrl, headers=self.headers, proxies=self.getProxy())
            response.encoding = 'utf-8'

            # response = requests.get(self.startUrl, headers=self.headers)
            if response.status_code != 200:
                default_logger.warning("状态码错误，连接异常！")
            if "window.location.href='https://passport.jd.com/new/login.aspx" in response.text:
                if self.retryCount >= self.retryMaxCount:
                    default_logger.warning(f"已超出最大尝试次数，退出 {self.startUrl}")
                    return None
                sleep = random.randint(5, 10)
                default_logger.warning(f"触发预警，等待 {sleep}秒")
                self.retryCount += 1
                time.sleep(sleep)
                return self.getId()
            html = etree.HTML(response.text)
            return html.xpath('//div[@class="search_prolist_item"]/@skuid')
        except Exception as e:
            default_logger.warning(e)
        return None

    def getData(self, maxPage, score,):  # maxPage是搜集评论的最大页数，每页10条数据。差评和好评的最大一般页码不相同，一般情况下：好评>>差评>中评
        # maxPage遇到超出的页码会自动跳出，所以设大点也没有关系。
        # score是指那种评价类型，好评3、中评2、差评1。
        if self.productsId == None:
            return None
        comments = []
        scores = []
        if len(self.productsId) < 4:  # limit the sum of products
            sum = len(self.productsId)
        else:
            sum = 3
        for j in range(sum):
            id = self.productsId[j]
            header = self.getHeaders(id)
            for i in range(1, maxPage):
                param, url = self.getParamUrl(id, i, score)
                default_logger.info("正在搜集第%d个商品第%d页的评论信息" % (j+1, i))
                try:
                    response = requests.get(url, headers=header, params=param)
                except Exception as e:
                    default_logger.warning(e)
                    break
                if response.status_code != 200:
                    default_logger.warning("状态码错误，连接异常")
                    continue
                time.sleep(random.randint(5, 10))  # 设置时延，防止被封IP
                if response.text == '':
                    default_logger.warning("未搜集到信息")
                    continue
                try:
                    res_json = json.loads(response.text)
                except Exception as e:
                    default_logger.warning(e)
                    continue
                if len((res_json['comments'])) == 0:
                    default_logger.warning("本页无评价数据，跳过")
                    break
                default_logger.info("正在搜集 %s 的%s信息" %
                                    (self.categlory, self.comtype[score]))
                for cdit in res_json['comments']:
                    comment = cdit['content'].replace(
                        "\n", ' ').replace('\r', ' ')
                    comments.append(comment)
                    scores.append(cdit['score'])
        # savepath = './'+self.categlory+'_'+self.comtype[score]+'.csv'
        default_logger.warning("已搜集%d条%s信息" %
                               (len(comments), self.comtype[score]))
        # 存入列表,简单处理评价
        remarks = []
        for i in range(len(comments)):
            rst = comments[i]
            rst = re.findall(zhon.hanzi.sentence, comments[i])
            if len(rst) == 0 or rst == ['。'] or rst == ['？'] or rst == ['！'] or rst == ['.'] or rst == [','] or rst == ['?'] or rst == ['!']:
                #default_logger.warning("拆分失败或结果不符(去除空格和标点符号)：%s" % (rst))
                continue
            else:
                remarks.append(rst)
        result = self.solvedata(remarks=remarks)
        if len(result) == 0:
            default_logger.warning("当前商品没有评价,使用默认评价")
            result = ["考虑买这个$之前我是有担心过的，因为我不知道$的质量和品质怎么样，但是看了评论后我就放心了。",
                      "买这个$之前我是有看过好几家店，最后看到这家店的评价不错就决定在这家店买 ",
                      "看了好几家店，也对比了好几家店，最后发现还是这一家的$评价最好。",
                      "看来看去最后还是选择了这家。",
                      "之前在这家店也买过其他东西，感觉不错，这次又来啦。",
                      "这家的$的真是太好用了，用了第一次就还想再用一次。",
                      "收到货后我非常的开心，因为$的质量和品质真的非常的好！",
                      "拆开包装后惊艳到我了，这就是我想要的$!",
                      "快递超快！包装的很好！！很喜欢！！！",
                      "包装的很精美！$的质量和品质非常不错！",
                      "收到快递后迫不及待的拆了包装。$我真的是非常喜欢",
                      "真是一次难忘的购物，这辈子没见过这么好用的东西！！",
                      "经过了这次愉快的购物，我决定如果下次我还要买$的话，我一定会再来这家店买的。",
                      "不错不错！",
                      "我会推荐想买$的朋友也来这家店里买",
                      "真是一次愉快的购物！",
                      "大大的好评!以后买$再来你们店！(￣▽￣)",
                      "真是一次愉快的购物！"
                      ]
        return result

    def solvedata(self, remarks):
        # 将数据拆分成句子
        sentences = []
        for i in range(len(remarks)):
            for j in range(len(remarks[i])):
                sentences.append(remarks[i][j])
        #default_logger.info("搜集的评价结果：" + str(sentences))
        return sentences

        # 存入mysql数据库
        '''
        db = pymysql.connect(host='主机名',user='用户名',password='密码',db='数据库名',charset='utf8mb4')
        mycursor = db.cursor()
        mycursor.execute("use jd") # 根据自己的数据库名称更改
        mycursor.execute("TRUNCATE table jd")
        for i in range(len(comments)):
            sql = "insert into jd(i,scores,comments) values('%s','%s','%s')"%(id,scores[i],comments[i]) # 根据自己的表结构更改
            try:
                mycursor.execute(sql)
                db.commit()
            except Exception as e:
                logging.warning(e)
                db.rollback()
        mycursor.close()
        db.close()
        logging.warning("已存入数据库")
        '''

        # 存入csv文件
        '''    
        with open(savepath,'a+',encoding ='utf8') as f:
            for i in range(len(comments)):
                f.write("%d\t%s\t%s\n"%(i,scores[i],comments[i]))
        logging.warning("数据已保存在 %s"%(savepath))
        '''


# 测试用例
if __name__ == "__main__":
    jdlist = [
        '笔筒台灯插座 手机支架多功能USB充电LED护眼灯遥控定时学生学习阅 读灯宿舍寝室卧室床头书桌台灯插排 笔筒台灯 4插位+2USB 1.8米（不带遥控）']
    for item in jdlist:
        spider = JDSpider(item, '__jdu=16403287719711842161742; pinId=yMslOeksx2QqDCBqdx3rgw; shshshfpa=77facf6b-75fd-2695-b033-aa4b7338f0ca-1625041840; shshshfpb=vhBSZuWVvUYTQ6S9N9n8FEQ==; unick=一只小迷糊虫; _tp=OhZUpi+1u1GAOjBe/VKVeK9QQr8J8ju0+Ebq/BR4Jbs=; _pst=king学佳; mt_xid=V2_52007VwMVV1xaUVMZTxlUA2cDG1deWFVaGUwabFFjARtTCAxbRhtOGwwZYgAXVkFRU1pPVRsOUGcBFQJfCAVdGnkaXQZkHxNaQVtbSx9OElkCbAYRYl9oUmocTx9eB2QGGltcaFJTG04=; pin=king学佳; ceshi3.com=201; unpl=JF8EAKNnNSttChxUBxoAThdEQ1lUWwoBSx9Ta2ACVQgPS1NREgIfExl7XlVdXhRKHx9tZhRUWlNLUw4YAisSEHteVV1cDEweBmtnNWReWUoZBRoDdRBde15Ublw4SxAGbmUGXVteS1wDGwISFxNLWlRYWAt7JwNmZDVkbVl7VTUaMlp8EEpdUFtbDUJaA2hiBFZeUU1SBRMEGxIZTl5UWV0OThQzblcG; __jdv=209449046|kong|t_2020568451_|jingfen|cf1303d4e9514f819a5660df16e81508|1664525782294; areaId=1; PCSYCityID=CN_110000_110100_110108; ipLoc-djd=1-2800-55811-0; TrackID=1-AmSGkwoyofDtNQZfqz_kGymrCfCYawDLbkoevfpKl4dyCTWF5ufIS6GoG6upC7wGvbMapSdJd5dAdPbSdzQQuGKd4lsxyR3hbwUZK1aaLLsqXGiAuUs6rPhhRLbNM-4; jwotest_product=99; JSESSIONID=94BB22C565B8D01789146E29DF49FB38.s1; __jdc=122270672; shshshfp=849e9347f53cd0ca8756daee26494793; __jda=122270672.16403287719711842161742.1640328771.1665200353.1665208716.102; thor=22C97D522355C7CE92F2393BB1190960DC2E419392C14783DB787A93A820C69CFD1F55219831A057B3E1440C59497CE92C641626BDC551A21C5A704A3B3ABE092252B0C718CB48557A456A89CF7D9AF2CFA9E56522F2E7154C6BC5BDDD1C51C16B9DB19E601627AAA282295244BDF8E764BD894D7E31D82EECD5E7E1AC56E65F; 3AB9D23F7A4B3C9B=NJJ3IO3FWQH5W3B37XQ7F7FFOEKK7S7PDR6UE2A6Y656IUXDUFK5KLVC6QBUZJCGZCWO2GKJMRSK2LWOR655QNPPE4; __jdb=122270672.4.16403287719711842161742|102.1665208716')
        spider.getData(4, 3)
