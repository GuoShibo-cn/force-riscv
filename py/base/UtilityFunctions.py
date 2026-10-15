#
# Copyright (C) [2020] Futurewei Technologies, Inc.
#
# FORCE-RISCV is licensed under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance
#  with the License.  You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES
# OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import RandomUtils


# Python integers can be arbitrarily large, so mask_to_size removes the upper
# bits to keep the value within a certain range.
def mask_to_size(aValue, aSize):
    return aValue & (2 ** aSize - 1)


def shuffle_list(aList):
    # The random module is used here to provide the shuffling algorithm using
    # the back end RandomUtils module to handle the random number generation.
    # The random module itself should not be used for random number generation!
    list_copy = list(aList)
    for i in range(len(list_copy) - 1, 0, -1):
        swap_index = RandomUtils.random32(0, i)
        list_copy[i], list_copy[swap_index] = list_copy[swap_index], list_copy[i]
    return list_copy
