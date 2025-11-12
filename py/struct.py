class struct:
    def __init__(self, a: str):
        self.a: str = a
    
    def tust(self):
        return self.a

s = struct(5)

s.a
s.tust()

s.a.capitalize().lower()
