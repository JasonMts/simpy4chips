from simpy import Environment
from Components.BasicComponent import Unit
from Components.Packets import BasePacket
from Components.Pipelines import FlowControlledPipeline
from Components.Buffers import FlowControlledBuffer


class TestFlowControl(Unit):

    def __init__(self,env,name='TestFlowControl',parent=None):

        Unit.__init__(self,env,name,parent)
        self.dataBuff=FlowControlledBuffer(env, 'Buffer',capacity=4, putBytesPerCycle=1,getBytesPerCycle=1)
        self.pipe=FlowControlledPipeline(env, 'Pipe', putBytesPerCycle=1,initCredits=4, depth=8)
        self.connect(fromUnit=self.pipe,toUnit=self.dataBuff)
    def run(self):

        self.env.process(self.sendProcess())
        yield self.env.process(self.retrievalProcess())

    def sendProcess(self):

        for idx in range(10):
            pkt=BasePacket()
            yield self.pipe.put(pkt)
            print('@{} : Finished sending packet {} down the pipeline'.format(self.env.now,idx))

    def retrievalProcess(self):
        idx=0
        while True:
            pkt=yield self.dataBuff.get()
            print('@{} : Reading packet {} from the buffer. Sending a credit back to the source'.format(self.env.now,idx))
            idx+=1



env=Environment()

TestFlowControl(env)

env.run(until=1000)
