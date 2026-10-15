FORCE_DIR = ../../../..
ARCH_ENUM = RISCV
include $(FORCE_DIR)/utils/make/Makefile.common

INC_PATHS = -I$(FORCE_DIR)/riscv/inc -I$(FORCE_DIR)/base/inc -I$(FORCE_DIR)/3rd_party/inc -I$(FORCE_DIR)/utils/handcar -I$(PYTHON_INC)
CORE_SRCS = $(filter-out main.cc Log.cc,$(notdir $(wildcard $(FORCE_DIR)/riscv/src/*.cc $(FORCE_DIR)/base/src/*.cc $(FORCE_DIR)/3rd_party/src/*.cc)))
CORE_OBJS = $(addprefix $(FORCE_DIR)/riscv/make_area/obj/,$(CORE_SRCS:.cc=.o)) $(FORCE_DIR)/riscv/make_area/utils/handcar/UopInterface.o

.PHONY: all core
all: bin/TwoStageAllocation_test
core:
	$(MAKE) -C $(FORCE_DIR)/riscv PICKY= make_dir
	$(MAKE) -C $(FORCE_DIR)/riscv PICKY= ../bin/friscv

bin/TwoStageAllocation_test: core TwoStageAllocation_test.cc
	@mkdir -p bin
	$(CC) $(CFLAGS) -DUNIT_TEST -DFORCE_TEST_ROOT='"$(abspath $(FORCE_DIR))"' $(INC_PATHS) -o $@ TwoStageAllocation_test.cc $(FORCE_DIR)/base/src/Log.cc $(CORE_OBJS) $(LFLAGS)
