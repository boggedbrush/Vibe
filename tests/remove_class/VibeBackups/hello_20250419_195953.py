# hello.py
def greet(name):
    print(f"Hello, {name}!)  # notice missing paren?

class OldClass:
    def foo(self):
        return 42

class Greeter:
    def __init__(self, name):
        print(f'Hello {name}')
