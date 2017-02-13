#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
一个轻量级,wsgi(Web Server Gateway Interface)兼容的web框架
web框架概要
	工作方式:wsgi server --> wsgi处理函数
	作用:将http原始请求 解析 响应 这些交给wsgi server处理
	     让我们专心用python编写web业务(wsgi处理函数)
	     所以wsgi是http的一种高级封装
	例子:
		wsgi处理函数
			def application(environ,start_response):
				method = environ['REQUEST_METHOD']
				path = environ['PATH_INFO']
				if method == 'GET' and path == '/':
					return handle_home(environ,start_response)
				if method == 'POST' and path == '/signin':
					return handle_signin(environ,start_response)
		
		wsgi server
			def run(self,port = 9000,host = '127.0.0.1'):
				from wsgiref.simple_server import make_server
				server = make_server(host,port,application)
				server.serve_forever()
设计web框架原因:
	1.wsgi提供的接口虽然比http接口高级,但和web app的处理逻辑比.还是比较低级
	  我们需要在wsgi接口之上能进一步抽象,让我们专注与用一个处理函数处理一个url,
	  至于url到函数的映射,就交给web框架来做

设计web框架接口:
	1.url路由:用于url到处理函数的映射
	2.url截拦:用于根据url做权限检测
	3.视图:用于html页面生成
	4.数据模型:用于抽取数据(model.py)
	5.事物数据:request数据和response数据的封装(threadlocal)
"""

import types,os,re,cgi,sys,time,datatime,functools,mimetypes,threading,logging,traceback,urllib

from db import Dict
import utils

try:
	from cStringIO import cStringIO
except ImportError:
	from StringIO import StringIO

ctx = threading.local()


