import sys
import traceback
try:
  import fisher_py
  print('Success!')
except Exception as e:
  print(f'Error: {e}')
  traceback.print_exc()
