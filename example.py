from kitHttp import KitHttp


class Example(KitHttp):
    def __init__(self):
        super().__init__()


if __name__ == "__main__":
    example = Example()
    example.run()
