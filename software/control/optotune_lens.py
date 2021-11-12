''' 
Serial communication protocol to control optotune liquid lens

- by Deepak Krishnamurthy
- updated by Hongquan Li July 2021

'''
import serial 	
import platform
import sys
import time
import numpy as np
import warnings
import serial.tools.list_ports
from control._def import *

class optotune_lens:
	# A class for serial control of optotune liquid lens

	def __init__(self, freq = 0, amp = 0, offset = 0):

		self.serialconn = None
		self.lensConnected = False

		self.freq = freq
		self.amp = amp
		self.offset = offset

		# Scale factor to translate an amplitude (in microns) to a lower and upper value of current (in 12 bit int -4096 to 4096)
		self.current_to_code_scalling_factor = 292.84/4095 # 292.84 mA for code 4095
		self.current_range_min = -250
		self.current_range_max = 250
		self.op_range_min = -2
		self.op_range_max = 3

		self.current_mA = 0

		# Auto-detect the lens-driver
		for p in serial.tools.list_ports.comports():
			print(p)

		lens_ports = [
				p.device
				for p in serial.tools.list_ports.comports()
				if 'Optotune' in p.description]
		
		if not lens_ports:
			# raise IOError()
			warnings.warn("No Optotune lens found")
			self.lensConnected = False

		else:
			print('Optotune lens driver found!')
			self.lensConnected = True
			self.serialconn = serial.Serial(lens_ports[0],115200)
			self.serialconn.close()
			self.serialconn.open()
			time.sleep(2.0)
			print('Serial Connection Open')

			# Establish Connection to the lens driver
			ok = self.handshake()

			if(ok):
				self.default_mode = "Sinusoid"
				self.mode = self.default_mode
				self.freq = freq
				self.amp = amp
				self.offset = offset

			else:
				warnings.warn("Connection to lens driver not successful")
		

	def sendData(self, data):
		if(self.lensConnected):
			self.serialconn.write(data)
		else:
			pass

	def recData(self, nBytes):
		if(self.lensConnected):
			data = bytearray(nBytes)
			for i in range(nBytes):
				data[i] = ord(self.serialconn.read())
			return data
		else:
			return None

	def handshake(self):

		start_cmd = bytearray("Start", 'utf-8')
		self.sendData(start_cmd)
		rec_data = self.recData(7)
		print(rec_data)
		if(rec_data == bytearray(b'Ready\r\n')):
			print('Handshaking complete')
			return True
		else:
			print('Failed to connect to lens driver')
			return False

	def split_int_4byte(self, number):
		byte0 = (number >> 24) & 0xFF
		byte1 = (number >> 16) & 0xFF
		byte2 = (number >> 8) & 0xFF
		byte3 = number & 0xFF
		
		# Highest byte is byte 0, byte3 is lowest
		return byte0, byte1, byte2, byte3

	def split_int_2byte(self,number):
		# HIGH Byte, LOW Byte
		return int(number) >> 8, int(number)% 256

	def split_signed_int_2byte(self,number):
		if abs(number) > 32767:
			number = np.sign(number)*32767

		if number!=abs(number):
			number=65536+number

		# HIGH Byte, LOW Byte
		return int(number) >> 8, int(number)% 256


	# new function - 2021
	def start_scanning(self,current_mA_min,current_mA_max,frequency_Hz):
		self.mode = "Sinusoid"
		self.sendMode()
		self.sendProperty("UpperCurr",current_mA_max/self.current_to_code_scalling_factor)
		self.sendProperty("LowerCurr",current_mA_min/self.current_to_code_scalling_factor)
		self.sendProperty("Freq",frequency_Hz)

	# new function - 2021
	def stop_scanning(self):
		self.set_current_mA(0) # this function stops the scanning

	# new function - 2021
	def set_current_mA(self,value):
		self.current_mA = value
		current_code = self.current_mA/self.current_to_code_scalling_factor
		self.mode = "DC"
		self.sendMode()
		self.sendCurrent(current_code)

	def changeMode(self, mode):
		self.mode = mode
		self.sendMode()

	def set_Freq(self, freq):
		self.freq = freq
		self.sendProperty("Freq",self.freq)
		print('set new freq of liquid lens: {}'.format(self.freq))

	def set_Amp_mA(self, amp_mA):
		self.upper_curr = int((amp_mA/2)/self.current_to_code_scalling_factor)
		self.lower_curr = -int((amp_mA/2)/self.current_to_code_scalling_factor)
		self.sendProperty("UpperCurr",self.upper_curr)
		self.sendProperty("LowerCurr",self.lower_curr)
		print('set new amplitude of liquid lens:low {}, high {}'.format(self.lower_curr, self.upper_curr))

	def sendMode(self):
		cmd = bytearray(4) # Data array 
		cmd[0], cmd[1] = ord('M'),ord('w')
		cmd[3] = ord('A')

		if self.mode == "Sinusoid":
			cmd[2] = ord('S')
		elif self.mode == "Square":
			cmd[2] = ord('Q')
		elif self.mode == "DC":
			cmd[2] = ord('D')
		elif self.mode == "Tringular":
			cmd[2] = ord('T')

		# print('Sent data without crc bytes: {}'.format(cmd))
		cmd_crc = self.addcrcCheckSum(cmd)
		# print('Sent data with crc bytes: {}'.format(cmd_crc))
		self.sendData(cmd_crc)

		if(self.lensConnected):
			rec_data = self.recData(7)
			rec_string = bytearray(3)
			rec_string[0], rec_string[1], rec_string[2] = cmd_crc[0],cmd_crc[2], cmd_crc[3]
			check = self.calculate_crc(rec_data[:5])
			if(rec_data[:3] == rec_string and check==0 ):
				print('Mode set successfully to : {}'.format(self.mode))
		else:
			pass


	def sendCurrent(self, value):
			cmd = bytearray(4) # Data array 
			cmd[0], cmd[1] = ord('A'),ord('w')
			cmd[2], cmd[3] = self.split_signed_int_2byte(value)
			cmd_crc = self.addcrcCheckSum(cmd)
			self.sendData(cmd_crc)
			print("Current set to {}".format(value))

	def sendProperty(self, prop, value):

		cmd = bytearray(8)
		# Property and Write Flags
		cmd[0], cmd[1] = ord('P'),ord('w')
		# Channel A flag
		cmd[3] = ord('A')

		if(prop=="UpperCurr"):
			cmd[2] = ord('U')
			# High to low bytes
			cmd[4], cmd[5] = self.split_signed_int_2byte(value)
			# Add zeros as stuffing bytes if changing the current
			cmd[6], cmd[7] = 0, 0
		elif(prop=="LowerCurr"):
			cmd[2] = ord('L')
			# High to low bytes
			cmd[4], cmd[5] = self.split_signed_int_2byte(value)
			# Add zeros as stuffing bytes if changing the current
			cmd[6], cmd[7] = 0, 0

		else:
			cmd[2] = ord('F')
			# High to Low bytes
			cmd[4], cmd[5], cmd[6], cmd[7] = self.split_int_4byte(int(1000*value)) # Since value needs to be sent in mHz

		# print('Sent data without crc bytes: {}'.format(cmd))
		cmd_crc = self.addcrcCheckSum(cmd)
		# print('Sent data with crc bytes: {}'.format(cmd_crc))
		self.sendData(cmd_crc)
		print("Set {} to {}".format(prop, value))
	
	def calculate_crc(self, data):
		crc_sum = 0
		for ii in range(len(data)):
			crc_sum = self.crc_16_update(crc_sum, data[ii])
		return crc_sum # crc checksum over all data elements

	def crc_16_update(self, crc, a):
		crc ^= a
		for ii in range(8):
			if (crc & 1):
				crc = (crc >> 1) ^ 0xA001
			else:
				crc = (crc >> 1)
		return crc

	def addcrcCheckSum(self, data):
		dataLen = len(data)
		# We need two more bytes to store the checksum 
		data_new = bytearray(dataLen + 2)
		crc_sum = self.calculate_crc(data)
		data_new[:dataLen] = data
		# For CRC Low byte first and then High byte
		# the int2byte function returns High Byte first
		data_new[dataLen + 1 ], data_new[dataLen] = self.split_int_2byte(crc_sum)

		return data_new

# For future, need to add this so one can switch between these two liquid lenses
# class varioptic_lens: