'''
Thinker is the main class for the whole running. Create a new instance of Thinker to start the thinking process.
'''
import re
from utils.AI_utils import ChatModel, get_chat, get_embedding_vector
from atoms import *
from data_struct.atom import *
from data_struct.value import *
from data_struct.converter import IntListConverter
from typing import Union
from data_struct.tree import Node, Tree
import copy
from utils.neo4j_utils import neo4j_session


class Thinker:

    def __init__(self, model:ChatModel=ChatModel.GPT3_5, temperature=0.5):
        self.model = model
        self.temperature = temperature

    # region private methods
    def _get_quoted_strs(self, s:str):
        '''get the strings quoted by []'''
        return re.findall(r'.*?\[(.*?)\].*?', s)

    def _init_think_output(self, question: str):
        prompt = f"""
        Suppose you are solving a problem using 'Chain of Thoughts' method, and you are now thinking the final outputs of the problem,
        which means that you are now reaching the solution of the problem.
        No calculation is required in this task. You are required to identify what types of final outputs should be
        Quote the final output with '[ ]'.

        e.g.
        ------------------
        Q: The sum of the price of a pen and a ball is 11. The price of the pen is 10 more than the price of the ball. What are the prices of the ball and pen?
        A: Final output : [Solution of system of linear equations of this problem].  
        ------------------
        Now, think about the final output of this question. You do
        Q: {question}
        Note that no explanation are required, just the final output is needed.
        """
        ret = get_chat(prompt, model=self.model, temperature=self.temperature)
        return self._get_quoted_strs(ret)[0]

    def _step_think_atom(self, question: str, situation: int, finishing_chain: list[Atom] = None):
        prompt = f"""
        Suppose you are solving a problem using 'Chain of Thoughts' method, and you will face two situation according the question stated.
        For the first situation (1), you have come to the last step of the chain(It means after this step, you will get the answer).
        During the last step, what method should you use to solve it? Give a brief description of the method or the name of the method as well as the inputs of the method.
        Try to think of what should have been done before the last step & what you will get after the last step so as to help you think of the last step.
        Quote the last step and corresponding inputs with '[ ][ ]'.
        
        -----------------
        For the second situation (2), you have given a group of finishing chains(It means after these chains or steps, you will get the answer and solve the problem).
        However, There are some missing chains connecting the finishing chains and initial chain.(Initial chain refers to the original problem, not the first step of the solution).
        You have to think the nearest chain to connect the finishing chains, so that the missing chains could be slowly found and whole problem could be solved.
        During this nearest step or chain, what method should you use to connect to the finishing chains?  Give a brief description of the method or the name of the method as well as the inputs of the method.
        Try to think what should be done before getting those finishing chains & what you will get after the nearest chain so the output of the nearest chain can be suited to the input of the head of finishing chains.
        Quote the nearest step and corresponding inputs with '[ ][ ]'.

        example 1:
        ------------------
        Q: 
        Problem: The sum of the price of a pen and a ball is 11. The price of the pen is 10 more than the price of the ball. What are the price of the ball and pen?
        Situation: 1
        A: Last step : [Solving system of linear equations][System of linear equations]. I should have listed out the equations before solving the last step. After finish the last step, I will get the value of the unknowns.
        ------------------
        
        example 2:
        ------------------
        Q:
        Problem: The sum of the price of a pen and a ball is 11. The price of the pen is 10 more than the price of the ball. What is the price of the ball?
        Situation: 2
        Groups of Finishing Chains: [Solving system of linear equation][System of linear equation]<-? 
        A: The nearest step: [Construct the system of linear equation][Short text describing the details of the equation]. 
        The final steps of this problem shown in finishing chains is solving system of linear equation with the required inputs, the sets of linear equation.
        I should have tried to figure out the text related to equation and then build up the equation sets for connecting the chain, fulfilling the inputs and then solve the linear equation later on.
        ------------------
        
        example 3:
        ------------------
        Q:
        Problem: 4 Cups of milk and 2 Coffee cost 70. 5 Cups of milk and 1 Coffee cost 60. Given that david have 70 dollars, How many possible cups of milk he can buy?
        Situation: 2
        Groups of Finishing Chains: [Calculation on a Formula][Formula of the integer division on 70 and Prices of cup of milk]<-[Solving system of linear equation][System of linear equation]<-?
        A: The nearest step: [Construct the system of linear equation][Short text describing the details of the equation].
        Two steps are given in the groups of the finishing chains. Final step of this problem is to do a calculation on integer division after we have solved the linear equation. Therefore, the chain of thought should be solving the linear equation and then do the calculation to know maximum number of milk David can buy.
        Therefore, to solve the linear equation and stated in the inputs part, we need to have the sets of equation first. Therefore, constructing the system of linear equation help connected the chains.
        ------------------
        Now, think about the question and answer the nearest step and input(s) of the chain of thoughts. Note that you don't need to answer the question and input(s) could be multiple if they can be summarized in single term and separated by a comma inside the same [ ].
        Q: {question}
        Situation: {situation}
        """
        if situation == 2:
            prompt += "Groups of Finishing Chains: "
            for chain in finishing_chain:
                prompt += f"[{chain.prompt}]["
                for i in range(len(chain.inputs)):
                    prompt += f"{chain.inputs[i].prompt}"
                    if i != len(chain.inputs)-1:
                        prompt += ","
                prompt += "]<-"
            prompt += "?"
        ret = get_chat(prompt, model=self.model, temperature=self.temperature)
        return self._get_quoted_strs(ret)

    def _information_match(self, problem: str, input_prompts: list):
        check = ""
        for i, input_prompt in enumerate(input_prompts):
            check += f"{i+1}. {input_prompt.prompt} \n"
        prompt_ = f"""
        Suppose you are playing a extraction game now. 
        You receive a problem in this game and some searching-information.
        For the problem given, it could be divided into two part, one is information part of the problem, one is question part of the problem. 
        Information part include the background of the problem mentioned. Question part are focusing on the question this problem would like to ask.
        You only need to focus on the information part.
        for each searching-information, you have to determine whether this searching-information exists in the information part of the problem stated.
        'Exist' here means that the information part of the problem provided or stated this searching-information.
        So, the procedure of this game is firstly breaking the whole problem into information and question parts and only focus on the information part. Secondly, you have to determine whether the searching information exists in the information part of the problem/ 
        Answer 1 if you think the existence for that searching-information occur, otherwise please answer 0.
        The searching-information could be multiple, with the number denoted.
        Quote the answer with '[ ]'. Answer for multiple searching-information should be separated by comma, in the same '[ ]'.
        
        Example 1 and 2 illustrate how 'Exist' mean in this game.
        example 1:
        ------------------
        Q: 
        Problem: The sum of the price of a pen and a ball is 11. The price of the pen is 10 more than the price of the ball. What is the price of the ball?
        Searching-information: 
        1. the system of the linear equation in mathematical format. 
        2. mathematics equations in text format.
        3. solution of the system of linear equation
        
        Answer : [0,1,0]
        
        Reason:
        The answer suggest that only searching-information 2 existed.
        Firstly, this problem could be broken into two parts, 
        for the information part:  "The sum of the price of a pen and a ball is 11. The price of the pen is 10 more than the price of the ball."
        for the question part: "What is the price of the ball?"
        
        For Searching-information 1. The system of linear equations in MATHEMATICAL format have NOT existed in the information part of the problem. mathematical equations, for example, '4x+5y=10/6x-7y=20' are NOT shown in this problem. Therefore 1 does NOT exist.
        For Searching-information 2. The text of mathematics equations are existed in the information part of the problem. "The sum of the price of a pen and a ball is 11. The price of the pen is 10 more than the price of the ball." is the mathematical equations in TEXT shown in the information part. Therefore 2 is given.
        For Searching-information 3, It is IMPORTANT to notice that solution of a problem is not existing in the information part. The solution of the equation are related to the answer of this problem which is needed to build up from the information given but not existed in that. Therefore, 3 does NOT exist.
        
        ------------------
        
        example 2:
        ------------------
        Q:
        Problem: using addition/subtraction/multiplication/division, how can we get 24 from 3,4,5,6?
        Searching-Information: 
        1. the list of integer used to build 24.
        2. The answer of the formula that build 24.
        Answer : [1,0]
        
        Reason:
        The answer suggested that information 1 exists.
        Firstly, this problem could be broken into two parts.
        for the information part, "Using addition/subtraction/multiplication/division", "3,4,5,6"
        for the question part, "how to get 24?"
        
        For Searching-information 1. The information part has given four numbers already, "3,4,5,6". Therefore 1 is given.
        For Searching-information 2, No formula that build 24 are shown in the information part. This searching-information is related to the answer of this problem which is needed to build up by hand, but not existing in the given information of the problem.
        -----------------
        
        Now, think on this extraction game.
        Q: 
        Problem: {problem}
        Information: 
        {check}
        
        A:(Your answer) 
        (Reason)
        -----------------
        """

        ret = get_chat(prompt_,model=self.model,temperature=self.temperature)
        ret = self._get_quoted_strs(ret)
        ret = NumListConverter.convert(ret)
        ret = [i for i in range(len(ret)) if ret[i] == 1]
        for index in sorted(ret, reverse=True):
            print(f"AI think {input_prompts[index]}, this input value could be fulfilled directly, no extra atom is required for this part")
            del input_prompts[index]

    def _create_promptedobject(self, promptetype: Union[Atom,Value], prompt_: str, sub_cls_name: str, input_value: list, output_value: list):
        if promptetype == Atom:
            class TempPromptedObject(promptetype):
                prompt = prompt_
                inputs = tuple(*input_value)
                outputs = tuple(*output_value)
        elif promptetype == Value:
            class TempPromptedObject(promptetype):
                prompt = prompt_
        else:
            return None

        TempPromptedObject.__qualname__ = sub_cls_name
        TempPromptedObject.cls_dict()[sub_cls_name] = TempPromptedObject
        return TempPromptedObject

    # endregion

    def thinking_process_ipo(self, question: str):

        '''
        Explain on some variables in this function
        output_value: usually the output_value of a atom
        input_value(s) : usually the input_value(s) of a atom
        output_prompt: prompt of the output of a atom given by chat_model
        input_prompt(s): prompt of the input(s) of a atom given by chat_model
        atom_prompt: prompt of the atom given by chat_model
        output_embed: embedding form of the prompt
        input_embed(s): embedding form of the prompt(s)
        atom_embed(s): embedding form of the prompt(s)
        thought: PromptedObj that will be used in solving this problem
        lists_of_thought: the list of storing unprocessed thought (Node of input/output value)
        chains_of_thought: Representing all the PromptedObj involved in this problem
        chains_of_atom: the descending list of atoms that will be involved in this problem
        '''

        lists_of_thought: list[Node,...] = []
        lists_of_value: list[Value,...] = []
        print("start thinking Q:", question)
        output = self._init_think_output(question)
        print("AI thinks the final output is:", output)
        output_embed = get_embedding_vector(output).tolist()
        ret = session.query_vector_index(f'{Value.BASE_CLS_NAME}_INDEX', output_embed,3,True,False)
        if ret[0][0]['score'] >= 0.9:
            output_value = Value.cls_dict()[ret[0][0]['name']]

        else:
            output_value = self.create_promptedobject(Value, output, output)
            cypher = output.create_subcls_cyphers()
            session.run(cypher)

        print(output_value, output_value.prompt)
        lists_of_value.append(output_value)
        thought = Node(output_value)
        lists_of_thought.append(thought)
        chains_of_thought = Tree(question, thought)
        chains_of_atom = []
        # TODO:: fix the chains of atom as well as the _step_think_prompt
        self._information_match(question, lists_of_value)

        while len(lists_of_value) > 0:
            value = lists_of_value.pop(0)
            print('current output_value needed: ', value.prompt)
            thought = lists_of_thought.pop(0)
            ret = session.query_linked_relationship(value.BASE_CLS_NAME, value.cls_name(), 'OUTPUT')
            list_of_atom = [Atom.cls_dict()[atom[0]] for atom in ret if atom[0] in Atom.cls_dict().keys()]
            print("atoms: ", list_of_atom)

            if len(list_of_atom) == 0:
                print("currently, no Atom with output relationship on that output Value")
                if len(chains_of_atom) == 0:
                    [atom_prompt, input_value_prompts] = self._step_think_atom(question, 1)
                else:
                    [atom_prompt, input_value_prompts] = self._step_think_atom(question, 2, chains_of_atom)

                atom = self.think_for_possible_func(atom_prompt, [value], False)

                if atom is None:
                    input_value_prompts = re.split(r'\s*,\s*', input_value_prompts)

                    input_value_lists = []
                    print(f"Creating new atom with {atom_prompt}")
                    for input_value_prompt in input_value_prompts:
                        input_value = self.create_promptedobject(Value, input_value_prompt, input_value_prompt)
                        cypher = input_value.create_subcls_cyphers()
                        session.run(cypher)
                        input_value_lists.append(input_value)

                    atom = self.create_promptedobject(Atom, atom_prompt, atom_prompt, input_value_lists, [value])
                    cypher = atom.create_subcls_cyphers()
                    session.run(cypher)
                    cypher1 = atom.build_output_relationship_value()
                    cypher2 = atom.build_input_relationship_value()
                    session.run(cypher1)
                    session.run(cypher2)

                else:
                    session.create_relationship('Value',value.cls_name(),'Atom',atom.cls_name(),'OUTPUT')
                    input_value_lists = session.query_linked_relationship(atom.BASE_CLS_NAME, atom.cls_name(), 'INPUT')
                    if input_value_lists is None:
                        raise Exception("Something goes wrong(input_value)")
                    else:
                        print(input_value_lists)
                        input_value_lists = [Value.cls_dict()[input_value[0]] for input_value in input_value_lists]

            else:
                if len(chains_of_atom) == 0:
                    [atom_prompt, input_value_prompts] = self._step_think_atom(question, 1)
                else:
                    [atom_prompt, input_value_prompts] = self._step_think_atom(question, 2, chains_of_atom)
                atom = self.think_for_possible_func(atom_prompt, [value], True, list_of_atom)
                if atom is None:
                    raise Exception("Something goes wrong(atom)")
                input_value_lists = session.query_linked_relationship(atom.BASE_CLS_NAME, atom.cls_name(), 'INPUT')
                if input_value_lists is None:
                    raise Exception("Something goes wrong(input_value)")
                else:
                    print(input_value_lists)
                    input_value_lists = [Value.cls_dict()[input_value[0]] for input_value in input_value_lists]

            print("Therefore, atom should be: ", atom.prompt)
            chains_of_atom.append(atom)
            new_thought = Node(atom)
            print(thought.promptedobj, thought.promptedobj.BASE_CLS_NAME, thought.child_print())
            print(new_thought.promptedobj, new_thought.promptedobj.BASE_CLS_NAME, new_thought.child_print())

            thought.insert_child(children=new_thought)
            print('----------------------------')
            print(thought.promptedobj, thought.promptedobj.BASE_CLS_NAME, thought.child_print())
            thought = copy.deepcopy(new_thought)
            print(new_thought.promptedobj, new_thought.promptedobj.BASE_CLS_NAME, new_thought.child_print())
            print("Input value of this atom should be", end=" ")
            for input_value in input_value_lists:
                print(input_value.prompt, end=" ")
                lists_of_value.append(input_value)
                new_thought = Node(input_value)
                thought.insert_child(children=new_thought)
                print(thought.promptedobj,thought.promptedobj.BASE_CLS_NAME,thought.child_print())
                lists_of_thought.append(new_thought)
            print("")
            self._information_match(question, lists_of_value)

        ret = chains_of_thought.run_the_tree()
        print("AI think the answer should be: ", ret)

    def think_for_possible_func(self, purpose:str, outputs, linked: True, lists_atom:[Atom,...] =[])->Atom:
        if linked:
            print('thinking for a suitable atom in linked_relationship...')
            possible_atoms = lists_atom
        else:
            print('thinking for a suitable atom...')
            possible_atoms = k_similar_atoms(purpose)
        print('possible atoms:', [atom.cls_name() for atom in possible_atoms])
        all_func_prompts = ""
        outputs_prompts = ','.join([f'{output.prompt}' for output in outputs])
        for j, atom in enumerate(possible_atoms):
            atom_input_prompts = '\n'.join([f'Input {i + 1}: {param.full_prompt}' for i, param in enumerate(atom.inputs)])
            atom_output_prompts = '\n'.join([f'Output {i + 1}: {param.full_prompt}' for i, param in enumerate(atom.outputs)])
            atom_prompt = atom.prompt
            all_func_prompts += f"""
                    Function {j + 1}:
                        Usage: {atom_prompt}
                        {atom_input_prompts}
                        {atom_output_prompts}
                    """
        prompt = f"""
        Now you are given some functions, which ONE do you think is able for reaching a given purpose's answer DIRECTLY?
        Consider more about the outputs of the functions whether could give you the answer directly. Note that a function may have many outputs, if the output required having inside the function outputs lists, then that function also could be chosen as one of the best.
        If none of them is possible, answer 'no', otherwise answer the function's index. Quote your answer & reason with two '[]'s. 

        example 1:
        ------------------
        Function 1:
            Usage: Solving system of linear equations
            Input 1: A system of linear equations (e.g. [x + y = 1, x - y = 2])
            Output 1: The solution of the linear equation set (e.g. {{x: 1, y: 0}})
        Function 2:
            Usage: Gives out an algebraic equation to represent your given text.
            Input 1: A text (e.g. 'A pen is 10 more expensive than a ball.')
            Input 2: A dictionary of variables (e.g. {{'x': 'pen', 'y': 'ball'}})
            Output 1: An algebraic equation (e.g. 'x = y + 10')
        Q: Purpose: Find a solution for {{"x-y=1", "x+y=2"}} Output: the solution of the system of linear equations
        A: [1]. [Because the output of function 1 is the solution of the linear equation set, which is the answer of the question.]
        ------------------

        example 2:
        ------------------
        Function 1:
            Usage: Solving system of linear equations
            Input 1: A system of linear equations (e.g. [x + y = 1, x - y = 2])
            Output 1: The solution of the linear equation set (e.g. {{x: 1, y: 0}})
        Function 2:
            Usage: Gives out an algebraic equation to represent your given text.
            Input 1: A text (e.g. 'A pen is 10 more expensive than a ball.')
            Input 2: A dictionary of variables (e.g. {{'pen': 'x', 'ball': 'y'}})
            Output 1: An algebraic equation (e.g. 'x = y + 10')
        Q: Purpose: A pen is 10 more expensive than a ball, and the sum of the price of a pen and a ball is 11. What is the price of the ball? Output: the price of the ball.
        A: [no]. [No function could be used directly.]
        ------------------

        Now, you are given the following funcs and purpose:
        ------------------
        {all_func_prompts}
        Purpose: {purpose} Outputs: {outputs_prompts}
        ------------------
        Note that you just need to give out the index of the function.
        """
        ret = self._get_quoted_strs(get_chat(prompt, model=self.model, temperature=self.temperature).strip())
        if len(ret)>1:
            ans, reason = ret[:2]
        else:
            ans, reason = ret[0], 'No reason.'
        if 'no' in ans.lower():
            print("AI thinks no function could be used directly.")
            return None
        else:
            atom = possible_atoms[IntConverter.convert(ans) - 1]
            print(f"AI thinks the function is: {atom.cls_name()}. "
                  f"Because: {reason}")
            return atom



