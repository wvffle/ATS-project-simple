map = {"s1"}


def add(list):
    all_children = set(list.children)
    pool = all_children.copy()
    i = 0
    while pool:
        child = pool.pop()
        all_children.add(child)
        pool.update(child.children)
        if "stmt:" in child.str():
            map["s1"].append(child)
            i = i + 1


def follows(s1: str, s2: str):
    i = 0
    while map:
        # print(map[2])
        if i + 1 < len(map):
            if s1 in map[i].str() and s2 in map[i + 1].str():
                print(i)
                return True
            else:
                return False
        i = i + 1
