#-----------------------------------------------------------
                #Basic Packet Class
#-----------------------------------------------------------
import math

class BasePacket(object):


    """A basic packet class that represent a packet with a header and payload.

    Arguments:

        * _headerbytes : number of bytes in the header of the packet
        * _payloadbytes: number of bytes in the payload of the packet
        *  f           : a dictionary of fields {fieldName:fieldValue} that can customized
        * uid: a unique identifier of the packet, incremented for each new instance of the class

    The packet has the following methods:
        * setSize(): customizable method to set the payload and headerbytes based on the fields with which the packet is initialized
        * getBytes(): returns the total number of bytes a packet contains (header + payload)
        * getTicks(bytesPerTick): takes as argument the width of the channel on which the packet is being transmitted 
                                  (number of bytes the channel sends per cycle(tick)) and returns the number of cycles
                                  it would take to complete sending it.

    
    This class can be extended with other variables and features to suit the purpose of the system being simulated and enhance 
    the logging features of the simulation. It does, however, present a minimal abstract concept of an object that can be transferred
    
   """

    nextuid=0
    def __init__(self, fields={}):

        self._payloadBytes=0
        self._headerBytes=0
        self.uid=self.nextid()
        self.f=fields
        self.setSize()

    def nextid(self):
        """Obtain the next unique packet id. Increments the class variable ==nextuid=="""
        uid = BasePacket.nextuid
        BasePacket.nextuid += 1
        return str(uid)

    def setSize(self):
        #sets the size of the header (if any) and the header (if any) in bytes
        self._payloadBytes = 1
        self._headerBytes  = 1

    def getBytes(self):
        #returns the size of the packet in bytes
        return self._payloadBytes+self._headerBytes

    def getTicks(self,bytesPerCycle):
        
        #returns the number of ticks processing the packet will take, where the processor's capability is provided as an argument (bytesPerCycle)

        return math.ceil(self.getBytes()/bytesPerCycle),0

