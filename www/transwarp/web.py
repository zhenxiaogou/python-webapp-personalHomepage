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
"""
实现事务数据接口,实现request数据和response数据的存储,是一个全局threadlocal对象
"""

_RE_RESPONSE_STATUS = re.compile(r'^\d\d\d(\ [\w\ ]+)?$')

_HEADER_X_POWERED_BY = ('X-Powered-By', 'transwarp/1.0')

_RESPONSE_STATUSES = {
    # Informational
    100: 'Continue',
    101: 'Switching Protocols',
    102: 'Processing',

    # Successful
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'No Content',
    205: 'Reset Content',
    206: 'Partial Content',
    207: 'Multi Status',
    226: 'IM Used',

    # Redirection
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    307: 'Temporary Redirect',

    # Client Error
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Timeout',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Precondition Failed',
    413: 'Request Entity Too Large',
    414: 'Request URI Too Long',
    415: 'Unsupported Media Type',
    416: 'Requested Range Not Satisfiable',
    417: 'Expectation Failed',
    418: "I'm a teapot",
    422: 'Unprocessable Entity',
    423: 'Locked',
    424: 'Failed Dependency',
    426: 'Upgrade Required',

    # Server Error
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
    505: 'HTTP Version Not Supported',
    507: 'Insufficient Storage',
    510: 'Not Extended',
}

_RESPONSE_HEADERS = (
    'Accept-Ranges',
    'Age',
    'Allow',
    'Cache-Control',
    'Connection',
    'Content-Encoding',
    'Content-Language',
    'Content-Length',
    'Content-Location',
    'Content-MD5',
    'Content-Disposition',
    'Content-Range',
    'Content-Type',
    'Date',
    'ETag',
    'Expires',
    'Last-Modified',
    'Link',
    'Location',
    'P3P',
    'Pragma',
    'Proxy-Authenticate',
    'Refresh',
    'Retry-After',
    'Server',
    'Set-Cookie',
    'Strict-Transport-Security',
    'Trailer',
    'Transfer-Encoding',
    'Vary',
    'Via',
    'Warning',
    'WWW-Authenticate',
    'X-Frame-Options',
    'X-XSS-Protection',
    'X-Content-Type-Options',
    'X-Forwarded-Proto',
    'X-Powered-By',
    'X-UA-Compatible',
)

class _HttpError(Exception):
	"""
	defines http error code
	e = _HttpError(404)
	e.status ==> '404 no found'
	"""
	def __init__(self,code):
		"""
		Init an HttpError with response code.
		"""
		super(_HttpError,self).__init__()
		self.status = '%d %s' % (code,_RESPONSE_STATUSES[code])
		self._headers = None 

	def header(self,name,value):
		"""
		添加header,如果header为空则添加power by header
		"""
		if not self._headers:
			self._headers = [_HEADER_X_POWERED_BY]
		self._headers.append((name,value))

	@property
	def headers(self,name,value):
		"""
		使用setter方法实现的header属性
		"""
		if hasattr(self,'_headers'):
			return self._headers
		return []

	def __str__(self):
		return self.status

	__repr__ = __str__

class _RedirectError(_HttpError):
	"""
	RedirectError that defines http redirect code
	e = _RedirError(302,'http://www.apple.com')
	e.status ==> '302 no found'
	e.location ==> 'http://www.apple.com'
	"""
	def __init__(self,code,location):
		"""
		Init an HttpError with response code.
		"""
		super(_RedirectError,self).__init__(code)
		sef.location = location

	def __str__(self):
		return '%s %s' % (self.status,self.location)

	__repr__ = __str__

class HttpError(object):
	"""
	HTTP Exceptions
	"""
	@staticmethod
	def badrequest():
		"""
		send a bad request response
		"""
		return _HttpError(400)

	@staticmethod
	def unauthorized():
		"""
		send an unauthorized response
		"""
		return _HttpError(401)

	@staticmethod
	def unforbiden():
		"""
		send an unforbiden response
		"""
		return _HttpError(403)

	@staticmethod
	def notfound():
		"""
		send an notfound response
		"""
		return _HttpError(404)

	@staticmethod
	def unauthorized():
		"""
		send an unauthorized response
		"""
		return _HttpError(401)

	@staticmethod
	def unauthorized():
		"""
		send an unauthorized response
		"""
		return _HttpError(401)

	@staticmethod
	def unauthorized():
		"""
		send an unauthorized response
		"""
		return _HttpError(401)

	@staticmethod
	def unauthorized():
		"""
		send an unauthorized response
		"""
		return _HttpError(401)

	@staticmethod
	def unauthorized():
		"""
		send an unauthorized response
		"""
		return _HttpError(401)


		
