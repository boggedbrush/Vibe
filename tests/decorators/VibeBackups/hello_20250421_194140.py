def foo(x):
    print(f'foo({x})')

def bar(x):
    print(f'bar({x})')


class MyClass:
    
    def compute(self, value):
        pass
    
    def old_method(self, *args):
        print('MyClass.old_method', *args)
