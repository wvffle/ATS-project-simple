from parser import parse

if __name__ == "__main__":
    parse(
        """
        procedure test {
            a = 8;
            while a {
                a = a + 1;
            }
        }
    """
    )
