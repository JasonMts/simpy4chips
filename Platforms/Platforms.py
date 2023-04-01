from Components.BasicComponent import Unit

class Platform(Unit):

    def __init__(self,env,name,parent):

        Unit.__init__(self,env,name,parent)

        self.units={}

    def insertUnit(self,unitinstance):

        unitType=type(unitinstance).__name__

        # if not unitType in self.units:
        #     self.units[unitType]={}

        self.units[unitinstance.name]=unitinstance
