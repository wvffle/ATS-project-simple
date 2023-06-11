from ats.ast import nodes
from ats.ast.nodes import ProcedureNode
from ats.pkb.utils import is_variable


def _dfs_noop(node: nodes.ASTNode, context: dict):  # pragma: no cover
    pass


def dfs(
    node: nodes.ASTNode,
    on_node_enter=_dfs_noop,
    on_node_exit=_dfs_noop,
):
    stack = []

    def _dfs(node: nodes.ASTNode):
        on_node_enter(node, {"stack": stack})
        stack.append(node)

        for child in node.children:
            _dfs(child)

        stack.pop()
        on_node_exit(node, {"stack": stack})

    _dfs(node)


def preprocess_query(tree: nodes.ProgramNode):
    statements_by_type = {
        "procedure": [],
        "variable": set(),
        "assign": [],
        "while": [],
        "stmt": [],
        "call": [],
        "if": [],
    }

    statements = {}
    procedures = {}
    variables = {}
    follows = {}
    calls = {}
    modifies = {}
    uses = {}
    next = {}
    proc_parents = {}
    proc_stmt_stack = []
    if_while_stack = []

    def find_statements():
        stmt_index = []
        stmt_id = 1
        proc_stmt_stack = []
        call_order = []

        def on_node_enter(node: nodes.ASTNode, context: dict):
            nonlocal stmt_id

            # Push the index to the stack when entering a statement list
            if isinstance(node, nodes.StmtLstNode):
                stmt_index.append(0)

            # Assign an index and a unique id to each statement
            if isinstance(node, nodes.StmtNode):
                statements[stmt_id] = node
                node.__stmt_id = stmt_id
                node.__stmt_index = stmt_index[-1]

                stmt_index[-1] += 1
                stmt_id += 1

                proc_stmt_stack.append(node)
                next[node] = []

                # procedure parents
                if isinstance(node, nodes.StmtCallNode):
                    if node.name in proc_parents:
                        proc_parents[node.name] += proc_stmt_stack
                    else:
                        proc_parents[node.name] = proc_stmt_stack[:]
                    # determining the order of call
                    # proc_stmt_stack[0] - procedure name in which is call
                    # node.name - call name
                    if (
                        proc_stmt_stack[0].name not in call_order
                        and node.name not in call_order
                    ):
                        call_order.append(proc_stmt_stack[0].name)
                        call_order.append(node.name)
                    elif (
                        proc_stmt_stack[0].name not in call_order
                        and node.name in call_order
                    ):
                        call_order.insert(
                            call_order.index(node.name), proc_stmt_stack[0].name
                        )
                    elif (
                        proc_stmt_stack[0].name in call_order
                        and node.name not in call_order
                    ):
                        call_order.insert(
                            call_order.index(proc_stmt_stack[0].name) + 1, node.name
                        )
                    else:
                        if call_order.index(node.name) < call_order.index(
                            proc_stmt_stack[0].name
                        ):
                            call_order.insert(
                                call_order.index(proc_stmt_stack[0].name) + 1, node.name
                            )
                        if call_order.index(node.name) > call_order.index(
                            proc_stmt_stack[0].name
                        ):
                            call_order.insert(
                                call_order.index(node.name), proc_stmt_stack[0].name
                            )

            # Find all variables
            if isinstance(node, nodes.VariableNode):
                variables[node] = node.name
                statements_by_type["variable"].add(node.name)

            # Find all procedures
            if isinstance(node, nodes.ProcedureNode):
                procedures[node.name] = node
                statements_by_type["procedure"].append(node)
                proc_stmt_stack.append(node)

            # Find all statements by type
            if isinstance(node, nodes.StmtNode):
                statements_by_type[node._type].append(node)
                statements_by_type["stmt"].append(node)

        def on_node_exit(node: nodes.ASTNode, context):
            # Pop the index from the stack when exiting a statement list
            if isinstance(node, nodes.StmtLstNode):
                stmt_index.pop()
            if isinstance(node, (nodes.ProcedureNode, nodes.StmtNode)):
                proc_stmt_stack.pop()

        dfs(
            tree,
            on_node_enter=on_node_enter,
            on_node_exit=on_node_exit,
        )

        # extending procedure parents with nested calls
        extend_parents = []
        for name in call_order:
            if name in proc_parents:
                proc_parents[name].extend(extend_parents)
                proc_parents[name] = list(set(proc_parents[name]))
                extend_parents.extend(proc_parents[name])
            else:
                extend_parents = []

    def process_relations():
        # Build stack with procedures name and statements id
        def on_node_enter(node: nodes.ASTNode, context: dict):
            if isinstance(node, nodes.ProcedureNode):
                proc_stmt_stack.append(node)

            if isinstance(node, nodes.StmtNode):
                proc_stmt_stack.append(node)

                # dict Next
                # if the node is the first child and its parent is statement
                # then the node is next for the parent
                if node.parent.children[0] == node and isinstance(
                    node.parent.parent, nodes.StmtNode
                ):
                    next[proc_stmt_stack[-2]].append(node)
            # dict Next
            if isinstance(node, nodes.StmtNode):
                if node.__stmt_index < len(node.parent.children) - 1:
                    # if current stmt in stmtLst is if stmt
                    # then add to stack if stmt node and next node
                    if isinstance(node, nodes.StmtIfNode):
                        if_while_stack.append(node)
                        if_while_stack.append(
                            node.parent.children[node.__stmt_index + 1]
                        )
                    # add current node to next for previous stmt in stmtLst
                    else:
                        next[node].append(node.parent.children[node.__stmt_index + 1])
            # dict Next
            if isinstance(node, nodes.StmtLstNode):
                if isinstance(node.parent, nodes.StmtWhileNode):
                    # if last child in while is if
                    # then add to stack while stmt node
                    if isinstance(node.children[-1], nodes.StmtIfNode):
                        if_while_stack.append(node.parent)
                        if_while_stack.append(node.parent)
                    # while is next for the last child
                    else:
                        next[node.children[-1]].append(node.parent)

            # Build the follows relation map
            if isinstance(node, nodes.StmtNode):
                if node.__stmt_index > 0:
                    follows[node] = node.parent.children[node.__stmt_index - 1]

            # Build the calls relation map
            if isinstance(node, nodes.StmtCallNode):
                caller = context["stack"][1]
                callee = procedures[node.name]

                # Disable recurrence
                if caller is not callee:
                    if callee not in calls:
                        calls[callee] = set()
                    calls[callee].add(caller)

        def on_node_exit(node: nodes.ASTNode, context):
            # dict Next
            if isinstance(node, nodes.StmtNode):
                if (
                    not isinstance(node, nodes.StmtIfNode)
                    and node.parent.children[-1] == node
                ):
                    # node is the last child in then stmtLst or else stmtLst
                    if node.parent.name == "then" or node.parent.name == "else":
                        if len(if_while_stack) > 0:
                            next[node].append(if_while_stack[-1])

            # if current node is the same as the last node on the stack
            if len(if_while_stack) > 0:
                if node == if_while_stack[-2]:
                    if_while_stack.pop()
                    if_while_stack.pop()

            # modifies and uses
            if isinstance(node, nodes.VariableNode):
                # modifies
                if node.parent.variable == node:
                    if node.name not in modifies:
                        modifies[node.name] = []
                    # adding the parents of the variable
                    modifies[node.name] = list(
                        set(proc_stmt_stack + modifies[node.name])
                    )
                    # extension of the dictionary with the parents of the current procedure
                    if proc_stmt_stack[0].name in proc_parents:
                        modifies[node.name] = list(
                            set(
                                proc_parents[proc_stmt_stack[0].name]
                                + modifies[node.name]
                            )
                        )
                # uses
                else:
                    if node.name not in uses:
                        uses[node.name] = []
                    # adding the parents of the variable
                    uses[node.name] = list(set(proc_stmt_stack + uses[node.name]))
                    # extension of the dictionary with the parents of the current procedure
                    if proc_stmt_stack[0].name in proc_parents:
                        uses[node.name] = list(
                            set(proc_parents[proc_stmt_stack[0].name] + uses[node.name])
                        )

            if isinstance(node, (nodes.ProcedureNode, nodes.StmtNode)):
                proc_stmt_stack.pop()

        dfs(tree, on_node_enter=on_node_enter, on_node_exit=on_node_exit)

    find_statements()
    process_relations()

    return {
        "statements_by_type": statements_by_type,
        "statements": statements,
        "variables": variables,
        "procedures": procedures,
        "follows": follows,
        "calls": calls,
        "uses": uses,
        "modifies": modifies,
        "next": next,
    }


def _get_stmt_type(query, parameter, default="stmt"):
    if parameter in query["variables"]:
        return query["variables"][parameter]
    else:
        return default


def map_result(node):
    if isinstance(node, nodes.StmtNode):
        return node.__stmt_id
    if isinstance(node, nodes.ProcedureNode):
        return node.name
    return node


# TODO: Handle with statements
def process_relation(
    query,
    context,
    relation,
    relation_cb,
    resolve_node,
    map_result=map_result,
    any_type="stmt",
):
    results = set()

    class Break(Exception):
        pass

    def get_needle(stmt_a, stmt_b):
        # Whem we explicitly ask for the second parameter
        if query["searching_variable"] == b:
            return stmt_b
        # Whem we explicitly ask for the first parameter, we ask for a BOOLEAN response or we ask for an unrelated variable
        return stmt_a

    def check_relation(stmt_a, stmt_b):
        nonlocal results

        try:
            if relation_cb(stmt_a, stmt_b):
                needle = query["searching_variable"]
                if needle == a or needle == b or needle == "BOOLEAN":
                    results.add(map_result(get_needle(stmt_a, stmt_b)))

                # NOTE: Edge case: We are querying some unrelated statement
                else:
                    results |= set(
                        map(
                            map_result,
                            context["statements_by_type"][
                                _get_stmt_type(
                                    query, query["searching_variable"], any_type
                                )
                            ],
                        )
                    )
                    raise Break()
        except KeyError:
            pass

    a, b = relation["parameters"]
    try:
        # NOTE: Best case scenario, we do not have to iterate at all, just static lookup
        if not is_variable(query, a) and not is_variable(query, b):
            stmt_a = resolve_node(a)
            stmt_b = resolve_node(b)
            check_relation(stmt_a, stmt_b)

        # NOTE: Worst case scenario, we have to iterate over all statements in O(n^2)
        #       We try to optimize it by iterating only over the statements
        #       of the specific type
        elif is_variable(query, a) and is_variable(query, b):
            for stmt_a in context["statements_by_type"][
                _get_stmt_type(query, a, any_type)
            ]:
                for stmt_b in context["statements_by_type"][
                    _get_stmt_type(query, b, any_type)
                ]:
                    check_relation(stmt_a, stmt_b)

        # NOTE: We have to iterate over all statements of only one type
        #       This is a case where we have a variable and a statement
        elif is_variable(query, a):
            stmt_b = resolve_node(b)
            for stmt_a in context["statements_by_type"][
                _get_stmt_type(query, a, any_type)
            ]:
                check_relation(stmt_a, stmt_b)

        # NOTE: We have to iterate over all statements of only one type
        #       This is a case where we have a statement and a variable
        elif is_variable(query, b):
            stmt_a = resolve_node(a)
            for stmt_b in context["statements_by_type"][
                _get_stmt_type(query, b, any_type)
            ]:
                check_relation(stmt_a, stmt_b)

    except Break:
        pass

    return results


def process_follows(query, context, relation):
    return process_relation(
        query,
        context,
        relation,
        lambda node_a, node_b: context["follows"][node_b] == node_a,
        lambda id: context["statements"][id] if id in context["statements"] else None,
    )


def process_follows_deep(query, context, relation):

    return process_relation(
        query,
        context,
        relation,
        lambda node_a, node_b: node_a.parent == node_b.parent and node_a.__stmt_index < node_b.__stmt_index
        lambda id: context["statements"][id],
    )


def process_parent(query, context, relation):
    return process_relation(
        query,
        context,
        relation,
        lambda node_a, node_b: node_b.parent.parent == node_a,
        lambda id: context["statements"][id] if id in context["statements"] else None,
    )


def process_parent_deep(query, context, relation):
    def relation_cb(node_a, node_b):
        node = node_b.parent.parent
        while not isinstance(node, ProcedureNode):
            if node == node_a:
                return True
            node = node.parent.parent
        return False

    return process_relation(
        query,
        context,
        relation,
        relation_cb,
        lambda id: context["statements"][id],
    )


def process_calls(query, context, relation):
    def resolve_node(param):
        if param[1:-1] not in context["procedures"]:
            return None

        return context["procedures"][param[1:-1]]

    return process_relation(
        query,
        context,
        relation,
        lambda node_a, node_b: node_b in context["calls"]
        and node_a in context["calls"][node_b],
        resolve_node,
        any_type="procedure",
    )


def process_calls_deep(query, context, relation):
    def resolve_node(param):
        return context["procedures"][param[1:-1]]

    def relation_cb(node_a, node_b):
        if node_b in context["calls"]:
            if node_a in context["calls"][node_b]:
                return True

            for call in context["calls"][node_b]:
                if relation_cb(node_a, call):
                    return True
        return False

    return process_relation(
        query,
        context,
        relation,
        relation_cb,
        resolve_node,
        any_type="procedure",
    )


def process_uses(query, context, relation):
    def resolve_node(param):
        if isinstance(param, int):
            return context["statements"][param]
        else:
            return param[1:-1]

    return process_relation(
        query,
        context,
        relation,
        lambda node_a, node_b: node_b in context["uses"]
        and node_a in context["uses"][node_b],
        resolve_node,
    )


def process_modifies(query, context, relation):
    def resolve_node(param):
        if isinstance(param, int):
            return context["statements"][param]
        else:
            return param[1:-1]

    return process_relation(
        query,
        context,
        relation,
        lambda node_a, node_b: node_b in context["modifies"]
        and node_a in context["modifies"][node_b],
        resolve_node,
    )


def process_next(query, context, relation):
    return process_relation(
        query,
        context,
        relation,
        lambda node_a, node_b: node_a in context["next"]
        and node_b in context["next"][node_a],
        lambda id: context["statements"][id],
    )


def evaluate_query(node: nodes.ProgramNode, query):
    context = preprocess_query(node)
    all_results = set()
    for i, relation in enumerate(query["conditions"]["relations"]):
        results = all_results if i == 0 else set()
        if relation["relation"] == "Follows":
            results |= process_follows(query, context, relation)

        if relation["relation"] == "Follows*":
            results |= process_follows_deep(query, context, relation)

        if relation["relation"] == "Parent":
            results |= process_parent(query, context, relation)

        if relation["relation"] == "Parent*":
            results |= process_parent_deep(query, context, relation)

        if relation["relation"] == "Calls":
            results |= process_calls(query, context, relation)

        if relation["relation"] == "Calls*":
            results |= process_calls_deep(query, context, relation)

        if relation["relation"] == "Modifies":
            results |= process_modifies(query, context, relation)

        if relation["relation"] == "Uses":
            results |= process_uses(query, context, relation)

        if relation["relation"] == "Next":
            results |= process_next(query, context, relation)

        if results != all_results:
            all_results = all_results.intersection(results)

    if query["searching_variable"] == "BOOLEAN":
        return len(all_results) > 0

    return list(all_results)
