import platform
import serial
import serial.tools.list_ports
import time
import numpy as np
import threading

from control._def import *

from qtpy.QtCore import *
from qtpy.QtWidgets import *
from qtpy.QtGui import *

# add user to the dialout group to avoid the need to use sudo

# done (7/20/2021) - remove the time.sleep in all functions (except for __init__) to 
# make all callable functions nonblocking, instead, user should check use is_busy() to
# check if the microcontroller has finished executing the more recent command

# to do (7/28/2021) - add functions for configuring the stepper motors

class Microcontroller():    
    def __init__(self,parent=None):
        self.serial = None
        self.platform_name = platform.system()
        self.tx_buffer_length = MicrocontrollerDef.CMD_LENGTH
        self.rx_buffer_length = MicrocontrollerDef.MSG_LENGTH

        self._cmd_id = 0
        self._cmd_id_mcu = None # command id of mcu's last received command 
        self._cmd_execution_status = None
        self.mcu_cmd_execution_in_progress = False

        self.x_pos = 0 # unit: microstep or encoder resolution
        self.y_pos = 0 # unit: microstep or encoder resolution
        self.z_pos = 0 # unit: microstep or encoder resolution
        self.theta_pos = 0 # unit: microstep or encoder resolution
        self.button_and_switch_state = 0
        self.joystick_button_pressed = 0
        self.signal_joystick_button_pressed_event = False
        self.switch_state = 0

        # AUTO-DETECT the Arduino! Based on Deepak's code
        arduino_ports = [
                p.device
                for p in serial.tools.list_ports.comports()
                if 'Arduino Due' == p.description]
        if not arduino_ports:
            raise IOError("No Arduino found")
        if len(arduino_ports) > 1:
            print('Multiple Arduinos found - using the first')
        else:
            print('Using Arduino found at : {}'.format(arduino_ports[0]))

        # establish serial communication
        self.serial = serial.Serial(arduino_ports[0],2000000)
        time.sleep(0.2)
        print('Serial Connection Open')

        self.new_packet_callback_external = None
        self.terminate_reading_received_packet_thread = False
        self.thread_read_received_packet = threading.Thread(target=self.read_received_packet, daemon=True)
        self.thread_read_received_packet.start()
        
    def close(self):
        self.terminate_reading_received_packet_thread = True
        self.thread_read_received_packet.join()
        self.serial.close()

    def turn_on_illumination(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.TURN_ON_ILLUMINATION
        self.send_command(cmd)

    def turn_off_illumination(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.TURN_OFF_ILLUMINATION
        self.send_command(cmd)

    def set_illumination(self,illumination_source,intensity,r=None,g=None,b=None):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.SET_ILLUMINATION
        cmd[2] = illumination_source
        cmd[3] = int((intensity/100)*65535) >> 8
        cmd[4] = int((intensity/100)*65535) & 0xff
        self.send_command(cmd)

    def set_illumination_led_matrix(self,illumination_source,r,g,b):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.SET_ILLUMINATION_LED_MATRIX
        cmd[2] = illumination_source
        cmd[3] = min(int(r*255),255)
        cmd[4] = min(int(g*255),255)
        cmd[5] = min(int(b*255),255)
        self.send_command(cmd)

    '''
    def move_x(self,delta):
        direction = int((np.sign(delta)+1)/2)
        n_microsteps = abs(delta*Motion.STEPS_PER_MM_XY)
        if n_microsteps > 65535:
            n_microsteps = 65535
        cmd = bytearray(self.tx_buffer_length)
        cmd[0] = CMD_SET.MOVE_X
        cmd[1] = direction
        cmd[2] = int(n_microsteps) >> 8
        cmd[3] = int(n_microsteps) & 0xff
        self.serial.write(cmd)
    '''

    def move_x_usteps(self,usteps):
        direction = STAGE_MOVEMENT_SIGN_X*np.sign(usteps)
        n_microsteps_abs = abs(usteps)
        # if n_microsteps_abs exceed the max value that can be sent in one go
        while n_microsteps_abs >= (2**32)/2:
            n_microsteps_partial_abs = (2**32)/2 - 1
            n_microsteps_partial = direction*n_microsteps_partial_abs
            payload = self._int_to_payload(n_microsteps_partial,4)
            cmd = bytearray(self.tx_buffer_length)
            cmd[1] = CMD_SET.MOVE_X
            cmd[2] = payload >> 24
            cmd[3] = (payload >> 16) & 0xff
            cmd[4] = (payload >> 8) & 0xff
            cmd[5] = payload & 0xff
            self.send_command(cmd)
            # while self.mcu_cmd_execution_in_progress == True:
            #     time.sleep(self._motion_status_checking_interval)
            n_microsteps_abs = n_microsteps_abs - n_microsteps_partial_abs

        n_microsteps = direction*n_microsteps_abs
        payload = self._int_to_payload(n_microsteps,4)
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.MOVE_X
        cmd[2] = payload >> 24
        cmd[3] = (payload >> 16) & 0xff
        cmd[4] = (payload >> 8) & 0xff
        cmd[5] = payload & 0xff
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)

    def move_x_to_usteps(self,usteps):
        payload = self._int_to_payload(STAGE_MOVEMENT_SIGN_X*usteps,4)
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.MOVETO_X
        cmd[2] = payload >> 24
        cmd[3] = (payload >> 16) & 0xff
        cmd[4] = (payload >> 8) & 0xff
        cmd[5] = payload & 0xff
        self.send_command(cmd)

    '''
    def move_y(self,delta):
        direction = int((np.sign(delta)+1)/2)
        n_microsteps = abs(delta*Motion.STEPS_PER_MM_XY)
        if n_microsteps > 65535:
            n_microsteps = 65535
        cmd = bytearray(self.tx_buffer_length)
        cmd[0] = CMD_SET.MOVE_Y
        cmd[1] = direction
        cmd[2] = int(n_microsteps) >> 8
        cmd[3] = int(n_microsteps) & 0xff
        self.serial.write(cmd)
    '''

    def move_y_usteps(self,usteps):
        direction = STAGE_MOVEMENT_SIGN_Y*np.sign(usteps)
        n_microsteps_abs = abs(usteps)
        # if n_microsteps_abs exceed the max value that can be sent in one go
        while n_microsteps_abs >= (2**32)/2:
            n_microsteps_partial_abs = (2**32)/2 - 1
            n_microsteps_partial = direction*n_microsteps_partial_abs
            payload = self._int_to_payload(n_microsteps_partial,4)
            cmd = bytearray(self.tx_buffer_length)
            cmd[1] = CMD_SET.MOVE_Y
            cmd[2] = payload >> 24
            cmd[3] = (payload >> 16) & 0xff
            cmd[4] = (payload >> 8) & 0xff
            cmd[5] = payload & 0xff
            self.send_command(cmd)
            # while self.mcu_cmd_execution_in_progress == True:
            #     time.sleep(self._motion_status_checking_interval)
            n_microsteps_abs = n_microsteps_abs - n_microsteps_partial_abs

        n_microsteps = direction*n_microsteps_abs
        payload = self._int_to_payload(n_microsteps,4)
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.MOVE_Y
        cmd[2] = payload >> 24
        cmd[3] = (payload >> 16) & 0xff
        cmd[4] = (payload >> 8) & 0xff
        cmd[5] = payload & 0xff
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)
    
    def move_y_to_usteps(self,usteps):
        payload = self._int_to_payload(STAGE_MOVEMENT_SIGN_Y*usteps,4)
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.MOVETO_Y
        cmd[2] = payload >> 24
        cmd[3] = (payload >> 16) & 0xff
        cmd[4] = (payload >> 8) & 0xff
        cmd[5] = payload & 0xff
        self.send_command(cmd)

    '''
    def move_z(self,delta):
        direction = int((np.sign(delta)+1)/2)
        n_microsteps = abs(delta*Motion.STEPS_PER_MM_Z)
        if n_microsteps > 65535:
            n_microsteps = 65535
        cmd = bytearray(self.tx_buffer_length)
        cmd[0] = CMD_SET.MOVE_Z
        cmd[1] = 1-direction
        cmd[2] = int(n_microsteps) >> 8
        cmd[3] = int(n_microsteps) & 0xff
        self.serial.write(cmd)
    '''

    def move_z_usteps(self,usteps):
        direction = STAGE_MOVEMENT_SIGN_Z*np.sign(usteps)
        n_microsteps_abs = abs(usteps)
        # if n_microsteps_abs exceed the max value that can be sent in one go
        while n_microsteps_abs >= (2**32)/2:
            n_microsteps_partial_abs = (2**32)/2 - 1
            n_microsteps_partial = direction*n_microsteps_partial_abs
            payload = self._int_to_payload(n_microsteps_partial,4)
            cmd = bytearray(self.tx_buffer_length)
            cmd[1] = CMD_SET.MOVE_Z
            cmd[2] = payload >> 24
            cmd[3] = (payload >> 16) & 0xff
            cmd[4] = (payload >> 8) & 0xff
            cmd[5] = payload & 0xff
            self.send_command(cmd)
            # while self.mcu_cmd_execution_in_progress == True:
            #     time.sleep(self._motion_status_checking_interval)
            n_microsteps_abs = n_microsteps_abs - n_microsteps_partial_abs

        n_microsteps = direction*n_microsteps_abs
        payload = self._int_to_payload(n_microsteps,4)
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.MOVE_Z
        cmd[2] = payload >> 24
        cmd[3] = (payload >> 16) & 0xff
        cmd[4] = (payload >> 8) & 0xff
        cmd[5] = payload & 0xff
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)

    def move_z_to_usteps(self,usteps):
        payload = self._int_to_payload(STAGE_MOVEMENT_SIGN_Z*usteps,4)
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.MOVETO_Z
        cmd[2] = payload >> 24
        cmd[3] = (payload >> 16) & 0xff
        cmd[4] = (payload >> 8) & 0xff
        cmd[5] = payload & 0xff
        self.send_command(cmd)

    def move_theta_usteps(self,usteps):
        direction = STAGE_MOVEMENT_SIGN_THETA*np.sign(usteps)
        n_microsteps_abs = abs(usteps)
        # if n_microsteps_abs exceed the max value that can be sent in one go
        while n_microsteps_abs >= (2**32)/2:
            n_microsteps_partial_abs = (2**32)/2 - 1
            n_microsteps_partial = direction*n_microsteps_partial_abs
            payload = self._int_to_payload(n_microsteps_partial,4)
            cmd = bytearray(self.tx_buffer_length)
            cmd[1] = CMD_SET.MOVE_THETA
            cmd[2] = payload >> 24
            cmd[3] = (payload >> 16) & 0xff
            cmd[4] = (payload >> 8) & 0xff
            cmd[5] = payload & 0xff
            self.send_command(cmd)
            # while self.mcu_cmd_execution_in_progress == True:
            #     time.sleep(self._motion_status_checking_interval)
            n_microsteps_abs = n_microsteps_abs - n_microsteps_partial_abs

        n_microsteps = direction*n_microsteps_abs
        payload = self._int_to_payload(n_microsteps,4)
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.MOVE_THETA
        cmd[2] = payload >> 24
        cmd[3] = (payload >> 16) & 0xff
        cmd[4] = (payload >> 8) & 0xff
        cmd[5] = payload & 0xff
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)

    def home_x(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.HOME_OR_ZERO
        cmd[2] = AXIS.X
        cmd[3] = int((STAGE_MOVEMENT_SIGN_X+1)/2) # "move backward" if SIGN is 1, "move forward" if SIGN is -1
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)
        #     # to do: add timeout

    def home_y(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.HOME_OR_ZERO
        cmd[2] = AXIS.Y
        cmd[3] = int((STAGE_MOVEMENT_SIGN_Y+1)/2) # "move backward" if SIGN is 1, "move forward" if SIGN is -1
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     sleep(self._motion_status_checking_interval)
        #     # to do: add timeout

    def home_z(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.HOME_OR_ZERO
        cmd[2] = AXIS.Z
        cmd[3] = int((STAGE_MOVEMENT_SIGN_Z+1)/2) # "move backward" if SIGN is 1, "move forward" if SIGN is -1
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)
        #     # to do: add timeout

    def home_theta(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.HOME_OR_ZERO
        cmd[2] = 3
        cmd[3] = int((STAGE_MOVEMENT_SIGN_THETA+1)/2) # "move backward" if SIGN is 1, "move forward" if SIGN is -1
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)
        #     # to do: add timeout

    def home_xy(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.HOME_OR_ZERO
        cmd[2] = AXIS.XY
        cmd[3] = int((STAGE_MOVEMENT_SIGN_X+1)/2) # "move backward" if SIGN is 1, "move forward" if SIGN is -1
        cmd[4] = int((STAGE_MOVEMENT_SIGN_Y+1)/2) # "move backward" if SIGN is 1, "move forward" if SIGN is -1
        self.send_command(cmd)

    def zero_x(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.HOME_OR_ZERO
        cmd[2] = AXIS.X
        cmd[3] = HOME_OR_ZERO.ZERO
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)
        #     # to do: add timeout

    def zero_y(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.HOME_OR_ZERO
        cmd[2] = AXIS.Y
        cmd[3] = HOME_OR_ZERO.ZERO
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     sleep(self._motion_status_checking_interval)
        #     # to do: add timeout

    def zero_z(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.HOME_OR_ZERO
        cmd[2] = AXIS.Z
        cmd[3] = HOME_OR_ZERO.ZERO
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)
        #     # to do: add timeout

    def zero_theta(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.HOME_OR_ZERO
        cmd[2] = AXIS.THETA
        cmd[3] = HOME_OR_ZERO.ZERO
        self.send_command(cmd)
        # while self.mcu_cmd_execution_in_progress == True:
        #     time.sleep(self._motion_status_checking_interval)
        #     # to do: add timeout

    def ack_joystick_button_pressed(self):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.ACK_JOYSTICK_BUTTON_PRESSED
        self.send_command(cmd)

    def analog_write_onboard_DAC(self,dac,value):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.ANALOG_WRITE_ONBOARD_DAC
        cmd[2] = dac
        cmd[3] = (value >> 8) & 0xff
        cmd[4] = value & 0xff
        self.send_command(cmd)

    def send_command(self,command):
        self._cmd_id = (self._cmd_id + 1)%256
        command[0] = self._cmd_id
        # command[self.tx_buffer_length-1] = self._calculate_CRC(command)
        self.serial.write(command)
        self.mcu_cmd_execution_in_progress = True

    def read_received_packet(self):
        while self.terminate_reading_received_packet_thread == False:
            # wait to receive data
            if self.serial.in_waiting==0:
                continue
            if self.serial.in_waiting % self.rx_buffer_length != 0:
                continue
            
            # get rid of old data
            num_bytes_in_rx_buffer = self.serial.in_waiting
            if num_bytes_in_rx_buffer > self.rx_buffer_length:
                # print('getting rid of old data')
                for i in range(num_bytes_in_rx_buffer-self.rx_buffer_length):
                    self.serial.read()
            
            # read the buffer
            msg=[]
            for i in range(self.rx_buffer_length):
                msg.append(ord(self.serial.read()))

            # parse the message
            '''
            - command ID (1 byte)
            - execution status (1 byte)
            - X pos (4 bytes)
            - Y pos (4 bytes)
            - Z pos (4 bytes)
            - Theta (4 bytes)
            - buttons and switches (1 byte)
            - reserved (4 bytes)
            - CRC (1 byte)
            '''
            self._cmd_id_mcu = msg[0]
            self._cmd_execution_status = msg[1]
            if (self._cmd_id_mcu == self._cmd_id) and (self._cmd_execution_status == CMD_EXECUTION_STATUS.COMPLETED_WITHOUT_ERRORS):
                if self.mcu_cmd_execution_in_progress == True:
                    self.mcu_cmd_execution_in_progress = False
                    print('   mcu command ' + str(self._cmd_id) + ' complete')

            # print('command id ' + str(self._cmd_id) + '; mcu command ' + str(self._cmd_id_mcu) + ' status: ' + str(msg[1]) )

            self.x_pos = self._payload_to_int(msg[2:6],MicrocontrollerDef.N_BYTES_POS) # unit: microstep or encoder resolution
            self.y_pos = self._payload_to_int(msg[6:10],MicrocontrollerDef.N_BYTES_POS) # unit: microstep or encoder resolution
            self.z_pos = self._payload_to_int(msg[10:14],MicrocontrollerDef.N_BYTES_POS) # unit: microstep or encoder resolution
            self.theta_pos = self._payload_to_int(msg[14:18],MicrocontrollerDef.N_BYTES_POS) # unit: microstep or encoder resolution
            
            self.button_and_switch_state = msg[18]
            # joystick button
            tmp = self.button_and_switch_state & (1 << BIT_POS_JOYSTICK_BUTTON)
            joystick_button_pressed = tmp > 0
            if self.joystick_button_pressed == False and joystick_button_pressed == True:
                self.signal_joystick_button_pressed_event = True
                self.ack_joystick_button_pressed()
            self.joystick_button_pressed = joystick_button_pressed
            # switch
            tmp = self.button_and_switch_state & (1 << BIT_POS_SWITCH)
            self.switch_state = tmp > 0

            if self.new_packet_callback_external is not None:
                self.new_packet_callback_external(self)

    def get_pos(self):
        return self.x_pos, self.y_pos, self.z_pos, self.theta_pos

    def get_button_and_switch_state(self):
        return self.button_and_switch_state

    def is_busy(self):
        return self.mcu_cmd_execution_in_progress

    def set_callback(self,function):
        self.new_packet_callback_external = function

    def _int_to_payload(self,signed_int,number_of_bytes):
        if signed_int >= 0:
            payload = signed_int
        else:
            payload = 2**(8*number_of_bytes) + signed_int # find two's completement
        return payload

    def _payload_to_int(self,payload,number_of_bytes):
        signed = 0
        for i in range(number_of_bytes):
            signed = signed + int(payload[i])*(256**(number_of_bytes-1-i))
        if signed >= 256**number_of_bytes/2:
            signed = signed - 256**number_of_bytes
        return signed

class Microcontroller_Simulation():
    def __init__(self,parent=None):
        self.serial = None
        self.platform_name = platform.system()
        self.tx_buffer_length = MicrocontrollerDef.CMD_LENGTH
        self.rx_buffer_length = MicrocontrollerDef.MSG_LENGTH

        self._cmd_id = 0
        self._cmd_id_mcu = None # command id of mcu's last received command 
        self._cmd_execution_status = None
        self.mcu_cmd_execution_in_progress = False

        self.x_pos = 0 # unit: microstep or encoder resolution
        self.y_pos = 0 # unit: microstep or encoder resolution
        self.z_pos = 0 # unit: microstep or encoder resolution
        self.theta_pos = 0 # unit: microstep or encoder resolution
        self.button_and_switch_state = 0
        self.joystick_button_pressed = 0
        self.signal_joystick_button_pressed_event = False
        self.switch_state = 0

         # for simulation
        self.timestamp_last_command = time.time() # for simulation only
        self._mcu_cmd_execution_status = None
        self.timer_update_command_execution_status = QTimer()
        self.timer_update_command_execution_status.timeout.connect(self._simulation_update_cmd_execution_status)

        self.new_packet_callback_external = None
        self.terminate_reading_received_packet_thread = False
        self.thread_read_received_packet = threading.Thread(target=self.read_received_packet, daemon=True)
        self.thread_read_received_packet.start()

    def close(self):
        self.terminate_reading_received_packet_thread = True
        self.thread_read_received_packet.join()

    def move_x_usteps(self,usteps):
        self.x_pos = self.x_pos + STAGE_MOVEMENT_SIGN_X*usteps
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': move x')

    def move_x_to_usteps(self,usteps):
        self.x_pos = STAGE_MOVEMENT_SIGN_X*usteps
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': move x to')

    def move_y_usteps(self,usteps):
        self.y_pos = self.y_pos + STAGE_MOVEMENT_SIGN_Y*usteps
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': move y')

    def move_y_to_usteps(self,usteps):
        self.y_pos = STAGE_MOVEMENT_SIGN_Y*usteps
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': move y to')

    def move_z_usteps(self,usteps):
        self.z_pos = self.z_pos + STAGE_MOVEMENT_SIGN_Z*usteps
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': move z')

    def move_z_to_usteps(self,usteps):
        self.z_pos = STAGE_MOVEMENT_SIGN_Z*usteps
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': move z to')

    def move_theta_usteps(self,usteps):
        self.theta_pos = self.theta_pos + usteps
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)

    def home_x(self):
        self.x_pos = 0
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': home x')

    def home_y(self):
        self.y_pos = 0
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': home y')

    def home_z(self):
        self.z_pos = 0
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': home z')

    def home_xy(self):
        self.x_pos = 0
        self.y_pos = 0
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': home xy')

    def home_theta(self):
        self.theta_pos = 0
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)

    def zero_x(self):
        self.x_pos = 0
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': zero x')

    def zero_y(self):
        self.y_pos = 0
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': zero y')

    def zero_z(self):
        self.z_pos = 0
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': zero z')

    def zero_theta(self):
        self.theta_pos = 0
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)

    def analog_write_onboard_DAC(self,dac,value):
        cmd = bytearray(self.tx_buffer_length)
        cmd[1] = CMD_SET.ANALOG_WRITE_ONBOARD_DAC
        cmd[2] = dac
        cmd[3] = (value >> 8) & 0xff
        cmd[4] = value & 0xff
        self.send_command(cmd)

    def read_received_packet(self):
        while self.terminate_reading_received_packet_thread == False:
            # only for simulation - update the command execution status
            if time.time() - self.timestamp_last_command > 0.05: # in the simulation, assume all the operation takes 0.05s to complete
                if self._mcu_cmd_execution_status !=  CMD_EXECUTION_STATUS.COMPLETED_WITHOUT_ERRORS:
                    self._mcu_cmd_execution_status = CMD_EXECUTION_STATUS.COMPLETED_WITHOUT_ERRORS
                    print('   mcu command ' + str(self._cmd_id) + ' complete')

            # read and parse message
            msg=[]
            for i in range(self.rx_buffer_length):
                msg.append(0)

            msg[0] = self._cmd_id
            msg[1] = self._mcu_cmd_execution_status

            self._cmd_id_mcu = msg[0]
            self._cmd_execution_status = msg[1]
            if (self._cmd_id_mcu == self._cmd_id) and (self._cmd_execution_status == CMD_EXECUTION_STATUS.COMPLETED_WITHOUT_ERRORS):
                self.mcu_cmd_execution_in_progress = False
            # print('mcu_cmd_execution_in_progress: ' + str(self.mcu_cmd_execution_in_progress))
            
            # self.x_pos = utils.unsigned_to_signed(msg[2:6],MicrocontrollerDef.N_BYTES_POS) # unit: microstep or encoder resolution
            # self.y_pos = utils.unsigned_to_signed(msg[6:10],MicrocontrollerDef.N_BYTES_POS) # unit: microstep or encoder resolution
            # self.z_pos = utils.unsigned_to_signed(msg[10:14],MicrocontrollerDef.N_BYTES_POS) # unit: microstep or encoder resolution
            # self.theta_pos = utils.unsigned_to_signed(msg[14:18],MicrocontrollerDef.N_BYTES_POS) # unit: microstep or encoder resolution
            
            self.button_and_switch_state = msg[18]

            if self.new_packet_callback_external is not None:
                self.new_packet_callback_external(self)

            time.sleep(0.005) # simulate MCU packet transmission interval

    def turn_on_illumination(self):
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': turn on illumination')

    def turn_off_illumination(self):
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': turn off illumination')

    def set_illumination(self,illumination_source,intensity):
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': set illumination')

    def set_illumination_led_matrix(self,illumination_source,r,g,b):
        cmd = bytearray(self.tx_buffer_length)
        self.send_command(cmd)
        print('   mcu command ' + str(self._cmd_id) + ': set illumination (led matrix)')

    def get_pos(self):
        return self.x_pos, self.y_pos, self.z_pos, self.theta_pos

    def get_button_and_switch_state(self):
        return self.button_and_switch_state

    def set_callback(self,function):
        self.new_packet_callback_external = function

    def is_busy(self):
        return self.mcu_cmd_execution_in_progress

    def send_command(self,command):
        self._cmd_id = (self._cmd_id + 1)%256
        command[0] = self._cmd_id
        # command[self.tx_buffer_length-1] = self._calculate_CRC(command)
        self.mcu_cmd_execution_in_progress = True
        # for simulation
        self._mcu_cmd_execution_status = CMD_EXECUTION_STATUS.IN_PROGRESS
        # self.timer_update_command_execution_status.setInterval(2000)
        # self.timer_update_command_execution_status.start()
        # print('start timer')
        # timer cannot be started from another thread
        self.timestamp_last_command = time.time()

    def _simulation_update_cmd_execution_status(self):
        # print('simulation - MCU command execution finished')
        # self._mcu_cmd_execution_status = CMD_EXECUTION_STATUS.COMPLETED_WITHOUT_ERRORS
        # self.timer_update_command_execution_status.stop()
        pass # timer cannot be started from another thread

