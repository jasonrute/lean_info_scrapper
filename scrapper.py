import subprocess
import json
import time
from datetime import datetime
import collections
import os
import sys
import gzip


class LeanServer:
    """
    Open up 
    a Lean server and communicate with it.  
    
    Right now it only has support for the "sync" and "info" requests (and their)
    corresponding responses.  It does however, store all "all_messages" response
    into a queue for later processing.
    """
    
    def __init__(self, options=None):
        self.cntr = -1
        self.cntr2 = -1
        self.all_messages = []
        self.all_messages_time = -1
        self.current_tasks = []
        self.current_tasks_time = -1
        
        lean_opts = []
        if options is not None:
            for name, value in options.items():
                lean_opts.append('-D')
                lean_opts.append(name + "=" + value)
        
        self.proc = subprocess.Popen(['lean', '--server'] + lean_opts, 
                    universal_newlines=True, 
                    stdin=subprocess.PIPE, # pipe STDIN and STDOUT to send and receive messages
                    stdout=subprocess.PIPE, 
                    #stderr=subprocess.PIPE
                )
        self.log = None
    
    # make into a context manager so that it closes lean server automatically
    def __enter__(self):
        self.proc.__enter__()
        return self
    
    def __exit__(self, type, value, traceback):
        self.proc.__exit__(type, value, traceback)
    
    def seq_num(self):
        self.cntr += 1
        return self.cntr
    
    def send_request(self, request, expected_response, verbose=False, sleep=0.0):
        seq_num = self.seq_num()
        request1 = request.copy()
        request1['seq_num'] = seq_num
        j = json.dumps(request1)
        
        # TODO: Use logging instead
        if self.log is not None:
            j_ = request1.copy()
            j_['_direction'] = 'sent'
            j_['_time'] = datetime.now().strftime('%H:%M:%S.%f')
            self.log.append(j_)
            
        if verbose:
            print()
            print("=>:", datetime.now().strftime('%H:%M:%S.%f'))
            pprint(j)
            print()
            
        # send
        print(j, file=self.proc.stdin, flush=True)
        
        # wait for response
        time.sleep(sleep)
        while True:
            self.cntr2 += 1
            raw_output = self.proc.stdout.readline()
            output = json.loads(raw_output)
            if self.log is not None:
                j_ = output.copy()
                j_['_direction'] = 'received'
                j_['_time'] = datetime.now().strftime('%H:%M:%S.%f')
                self.log.append(j_)
            if verbose:
                print("<=:", datetime.now().strftime('%H:%M:%S.%f'))
                pprint(output)
                print()
            if 'response' in output:
                if output['response'] == expected_response and output['seq_num'] == seq_num:
                    return output
                # TODO: Handle error differently.  It means the JSON is bad
                elif output['response'] == 'error':
                    return output
                # record messages since they may point to errors in the lean code
                elif output['response'] == 'all_messages':
                    self.all_messages = output['msgs']
                    self.all_messages_time = self.cntr2
                # record tasks to know when Lean has stopped processing file
                elif output['response'] == 'current_tasks':
                    self.current_tasks = output['tasks']
                    self.current_tasks_time = self.cntr2
    
    def send_sync_request(self, file_name, content, verbose=False):
        request = {
            'command':'sync',
            'file_name': file_name,
            "content": content,
        }
        
        return self.send_request(request, expected_response='ok', verbose=verbose, sleep=0.0)
    
    def send_info_request(self, file_name, line, column, verbose=False):
        request = {            
            'command':'info',
            'file_name': file_name,
            'column': column,
            'line': line
        }
        
        return self.send_request(request, expected_response='ok', verbose=verbose, sleep=0.0)


class LeanInfoScrapper:
    """
    Interface to scrap a Lean file (or multiple files)
    """
    def __init__(self, lean_options=None):
        self.lean_server = LeanServer(lean_options)
    
    # make into a context manager so that it closes lean server automatically
    def __enter__(self):
        self.lean_server.__enter__()
        return self
    
    def __exit__(self, type, value, traceback):
        self.lean_server.__exit__(type, value, traceback)
        
    def get_message_log_and_characters_from_file(self, file_name, file_contents):
        """
        Runs sync on a file, then runs info request on every position.
        
        Returns all server communication and all characters keyed by position.
        """
        
        # set up the lean server to log results
        self.lean_server.log = []
        
        self.lean_server.send_sync_request(
            file_name=file_name, 
            content=file_contents
        )
        
        time.sleep(1)
        
        characters = []
        for i, l in enumerate(file_contents.split("\n")):
            l = l + '\n'
            for j, c in enumerate(l):
                self.lean_server.send_info_request(
                    file_name=file_name, 
                    line=i+1, 
                    column=j)
                characters.append((i+1, j, c))

        return self.lean_server.log, characters
    
    def process_server_log(self, lean_server_log, characters, filename):
        """
        Process the server log and turn it into cleaned up messages.
        
        The result is a list of dictionary items of the form:
          {'file': <path_to_file>, 
           'line1': <start_line>, # start of message
           'col1': <start_col>,   #   both line and col are 1-indexed
           'line1': <start_line>, # position one character after end of message, 
           'col1': <start_col>,   #   both line and col are 1-indexed
           'info_type',           # type of message, e.g. 'state', 'full-id', 'type', 'source', 'doc', etc.
           'info_content',        # message content, may be a string, number, or dictionary.
           'string'               # the string spanned by the message
        """
        
        # get all outgoing info requests
        seq_nums = {}
        for comm in lean_server_log:
            if 'command' in comm and comm['command'] == 'info':
                seq_nums[comm['seq_num']] = comm['line'], comm['column']

        # get all incoming responses and match up with corresponding info request
        info_records = {}
        info_times = {}
        for comm in lean_server_log:
            if 'record' in comm:
                line, col = seq_nums[comm['seq_num']]
                info_records[line, col] = comm['record']
                info_times[line, col] = comm['_time']
    
        # an info record is made up of many individual info messages each 
        # keyed with a type, like 'state'.
        # go through each line, col position one at at time and trace how long each
        # individual info message goes for.  Record the start, end, and the string that
        # is spanned by that message.
        
        active_messages = {}  # messages which are still active (we haven't reach the end)
        all_messages = []     # the output of this method
        
        for (line, col, char) in characters:
            # get current messages (if any)
            if (line, col) in info_records:
                current_message_content = info_records[line, col].copy()
            else:
                current_message_content = {}
            
            # figure out if old messages have finished
            new_active_messages = {}
            for k in active_messages:
                if k in current_message_content and active_messages[k]['info_content'] == current_message_content[k]:
                    # message is still ongoing.
                    new_active_messages[k] = active_messages[k]
                    new_active_messages[k]['string'] += char
                else:
                    # message ended, add to output
                    active_messages[k]['line2'] = line
                    active_messages[k]['col2'] = col + 1  # add one to make it one =-indexed like line
                    all_messages.append(active_messages[k])

            # track any new messages
            for k in current_message_content:
                if k not in new_active_messages:
                    # message is still ongoing.
                    message = {
                        'file': filename, 
                        'info_type': k, 
                        'line1': line, 
                        'col1': col + 1,  # add one to make it one-indexed like line 
                        'info_content': current_message_content[k], 
                        'string': char,
                        '_timestamp': info_times[line, col]
                    }
                    new_active_messages[k] = message

            active_messages = new_active_messages
        
        return all_messages

    def process_file(self, file_name, file_content):
        """
        Process a "file".  Doesn't need to be a real file.  Could
        """
        log, chars = self.get_message_log_and_characters_from_file(file_name, file_content)
        msgs = self.process_server_log(log, chars, file_name)
        
        # TODO: I think this will blow up the memory unless I find a way to tell Lean to forget about the file
        return msgs
    
    def process_file_from_path(self, path):
        assert path.endswith(".lean")
        
        print('Processing', path, '...')
        
        with open(path, 'r') as f:
            return self.process_file(path, f.read())

    def process_directory_from_path(self, path):
        all_msgs = []
        for (root,dirs,files) in os.walk(path):
            for name in files:
                if name.endswith(".lean"):
                    file_path = os.path.join(root, name)
                    msgs = self.process_file_from_path(file_path)
                    all_msgs.extend(msgs)
        
        return all_msgs
    
    def msgs_to_json(self, msgs):
        return json.dumps(msgs)
    
    def msgs_to_json_file(self, msgs, file_path):
        json.dump(msgs, open(file_path,"w"))


def lean_paths():
    proc = subprocess.Popen(['lean', '--path'], 
                        universal_newlines=True, 
                        stdin=subprocess.PIPE, # pipe STDIN and STDOUT to send and receive messages
                        stdout=subprocess.PIPE, 
                        #stderr=subprocess.PIPE
                           )
    lines = proc.communicate()
    d = json.loads("".join(lines[:-1]))
    paths = []
    for p in d['path']:
        p2 = p.replace('/bin/..', '').replace("/./", "/")
        if os.path.isdir(p2):
            paths.append(p2)
    return paths
    
def output_file_name(path, lean_paths):
    for prefix in lean_paths:
        if path.startswith(prefix):
            remaining_path = path[len(prefix)+1:]
            return remaining_path.replace("/", "__").replace(".lean", ".json.gz")
    
    return None

def scrap_and_save_file(file_path, lean_paths):
    file_name_end = output_file_name(file_path, lean_paths)
    if file_name_end is None:
        raise Exception("File " + file_path + " must be an expension of one of these paths:\n", lean_paths)
            
    with LeanInfoScrapper({'pp.all':'true'}) as scrapper:
        msgs = scrapper.process_file_from_path(file_path)
        j = scrapper.msgs_to_json(msgs)
        output_file = output_directory + '/' + file_name_end

        print("Saving results to:", output_file)
        json.dump(msgs, gzip.open(output_file, 'wt'))

def scrap_and_save_directory(path, lean_paths):
    for (root, _, files) in os.walk(path):
        for name in files:
            if name.endswith(".lean"):
                file_path = os.path.join(root, name)
                scrap_and_save_file(file_path, lean_paths)

if __name__ == "__main__":
    _, path, output_directory = sys.argv

    lean_paths = lean_paths()

    if path == 'ALL':
        for lean_path in lean_paths:
            scrap_and_save_directory(lean_path, lean_paths)

    elif path.endswith('.lean'):
        scrap_and_save_file(path, lean_paths)

    elif os.path.isdir(path):
        scrap_and_save_directory(path, lean_paths)
        

