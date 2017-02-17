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
	def conflict():
		"""
		send an conflict response
		"""
		return _HttpError(409)

	@staticmethod
	def internalerror():
		"""
		raise HttpError.internalerror()
		traceback:
			...
		_HttpError:500 Internal Server Error
		"""
		return _HttpError(500)

	@staticmethod
	def redirect(location):
		"""
		raise HttpError.redirect('http://www.zhenxiaogou.com')
		traceback:
			..
		_RedirectError:301 Moved Permanently,http://www.zhenxiaogou.com
		"""
		return _RedirectError(301,location)

	@staticmethod
	def found(location):
		"""
		send an unauthorized response
		"""
		return _RedirectError(302,location)

	@staticmethod
	def seeother(location):
		"""
		do Temporary redirect
		"""
		return _RedirectError(303,location)

_RESPONSE_HEADER_DICT = dict(zip(map(lambda x: x.upper(), _RESPONSE_HEADERS), _RESPONSE_HEADERS))

class Request(object):
	def __init__(self,environ):
		self._environ = environ

	def _parse_input(self):
		"""
		将通过wsgi传入的参数解析成字典对象返回
		比如：request({'REQUEST_METHOD':'POST','wsgi.input':StringIO('a=1&b=Mjkjkjkjk')})
			这里解析的就是wsgi.input对象里面的字节流
		"""
			def _convert(item):
				if isinstance(item,list):
					return [utils.to_unicode(i,value) for i in item]
				if item.filename:
					return MultipartFile(item)
				return utils.to_unicode(item.value)
			fs = cgi.FieldStorage(fp=self._environ['wsgi.input'],environ=self._environ,keep_blank_values=True)
			inputs = dict()
			for key in fs:
				inputs[key] = _convert(fs[key])
			return inputs

	def _get_raw_input(self):
		if not hasattr(self,'_raw_input'):
			sefl._raw_input = self._parse_input()
		return self._raw_input

	def __getitem__(self,key):
		r = self._get_raw_input()[key]
		if isinstance(r,list):
			return r[0]
		return r

	def get(self,key,defalut=None):
		"""
		实现了字典里面的get功能
		"""
		r = self._get_raw_input().get(key,defalut)
		if isinstance(r,list):
			return r[0]
		return r

	def gets(self,key):
		r = self._get_raw_input()[key]
		if isinstance(r,list):
			return r[:]
		return [r]

	def input(self,**kw):
		copy = Dict(**kw)
		raw = self._get_raw_input()
		for k,v in raw.iteritems():
			cpoy[k] = v[0] if isinstance(v,list) else v
		return copy

	def get_body(self):
		"""
		从http post请求中取得body里面的数据，返回一个str对象
		"""
		fp = self._environ['wsgi.input']
		return fp.read()

	@property
	def remote_addr(self):
		return self._environ.get('REMOTE_ADDR','0.0.0.0')

	@property
	def document_root(self):
		return self._environ.get('DOCUMENT_ROOT','')

	@property
	def query_string(self):
		return self._environ.get('QUERY_STRING','')

	@property
	def environ(self):
		return self._environ

	@property
	def request_method(self):
		return self._environ['REQUEST_METHOD']

	@property
	def path_info(self):
		return urllib.unquote(self._environ.get('PATH_INFO',''))

	@property
	def host(self):
		return self._environ.get('HTTP_HOST','')

	def _get_headers(self):
		if not hasattr(self,'_headers'):
			hdrs = {}
			for k,v in self._environ.iteritems():
				if k.startswith('HTTP_'):
					hdrs[k[5:].replace('_','-').upper()] = v.decode('uft-8')
			self._headers = hdrs
		return self._headers

	@property
	def headers(self):
		return dict(**self._get_headers())

	def header(self,header,defalut=None):
		return self._get_headers().get(header.upper(),defalut)

	def _get_cookies(self):
		if not hasattr(self,'_cookies'):
			cookies = {}
			cookie_str = self._environ.get('HTTP_COOKIE')
			if cookie_str:
				for c in cookie_str.split(';'):
					pos = c.find('=')
					if pos > 0:
						cookies[c[:pos].strip()] = utils.unquote(c[pos+1:])
			self._cookies = cookies
		return self._cookies

	@property
	def cookies(self):
		return self._get_cookies().get(name,defalut)

class Response(object):

	def __init__(self):
		self._status = '200ok'
		self._headers = {'CONTENT-TYPE':'text/html;charset=utf-8'}

	def unset_header(self,name):
		key = name.upper()
		if key not in _RESPONSE_HEADER_DICT:
			key = name
		if key in self._headers:
			del self._headers[key]

	def set_header(self,name,value):
		key = name.upper()
		if key not in _RESPONSE_HEADER_DICT:
			key = name
		self._headers[key] = utils.to_str(value)

	def header(self,name):
		key = name.upper()
		if key not in _RESPONSE_HEADER_DICT:
			key = name
		return self._headers.get(key)

	@property
	def headers(self):
		L = [(_RESPONSE_HEADER_DICT.get(k,v)),v for k,v in self._headers.iteritems()]
		if hasattr(self,'_cookies'):
			for v in self._cookies.itervalues():
				L.append(('Set-Cookie',v))
		L.append(_HEADER_X_POWERED_BY)
		return L

	@property
	def content_type(self):
		return self.header('CONTENT-TYPE')

	@content_type.setter
	def content_type(self,value):
		if value:
			self.set_header('CONTENT-TYPE',value)
		else:
			self.unset_header('CONTENT-TYPE')

	@property
	def content_length(self):
		return self.header('CONTENT-LENGTH')

	@content_length.setter
	def content_length(self,value):
		self.set_header('CONTENT-LENGTH',str(value))

	def delete_cookie(self,name):
		self.set_cookie(name,'__delete__',expires=0)

	def set_cookie(self,name,value,max_age,expires=None,path='/',domain)	
	
	

	
	
	
	
	
	
	

		
