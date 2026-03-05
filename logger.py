import os

class Logger:
    def __init__(self, log_file):
        self.log_file = get_log_file(log_file)
        print(f'Logging to {self.log_file}')
        self.file_handler = open(self.log_file, 'w+', encoding='utf-8')

    def log(self, message):
       print(message)

       self.file_handler.write(message + '\n')
       self.file_handler.flush()

    def get_file_handler(self):
        return self.file_handler
    
    def close(self):
        self.file_handler.close()


def get_log_file(file_name):
    if os.environ.get('NOTDEV'):
        return f'{os.environ.get("TOOL_DATA_DIR")}/logs/{file_name}.log'
    else:
        return f'./logs/{file_name}'