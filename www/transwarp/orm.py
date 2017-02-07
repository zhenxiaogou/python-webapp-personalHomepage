#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
orm模块设计原因:
	1.简化操作
		sql操作的数据是 关系型数据,而python操作的是对象,为了简化编程需要对他们进行映射
		映射关系:
			表 ==> 行
			行 ==> 实例

设计orm接口:
	1.设计原则
		根据上层调用者设计简单易用的api接口
	2.设计调用接口
		1.表 <==> 类
			通过类的属性 来映射表的属性(表名,字段名,字段属性)
				from transwarp.orm import Model,StringField,IntegerField

				class ClassName(object):
					__table__ = 'users'
					id = IntegerField(primary_key=True)
					name = StringField()
			从中可以看出__table__拥有映射表名,id/name用于映射 字段对象(字段名和字段属性)
		2.行 <==> 实例
			通过实例的属性来映射行的值
				#创建实例
				user = User(id = 123,name = 'Michael')
				#存入数据库
				user.insert()
			最后 id/name 要变成user实例的属性
"""

class Model(dict):
	__metaclass__ = ModelMetaclass

	def __init__(self,**kw):
		super(Model,self).__init__(**kw)

	def __getattr__(self,key):
		try:
			return self[key]
		except KeyError:
			raise AttributeError(r"Dict object has no attribute '%s'" % key)

	def __setattr__(self,key,value):
		self[key] = value

class ModelMetaclass(type):
	def __new__(cls,name,bases,attrs):
		mapping

		
