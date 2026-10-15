#ifndef FORCE_HANDCAR_COSIM_WRAPPER_H
#define FORCE_HANDCAR_COSIM_WRAPPER_H

#include <cstdint>
#include <cstddef>

#ifdef __cplusplus
extern "C" {
#endif

// Callback types
typedef enum { MemRead = 0, MemWrite = 1, MemFetch = 2 } MemAccessType;

// Memory update callback
void update_generator_memory(uint32_t cpuid, uint64_t virtualAddress, uint32_t memBank, 
                             uint64_t physicalAddress, uint32_t size, const char *pBytes, const char *pAccessType);

// MMU event callback
typedef struct {
    uint64_t va;
    uint64_t pa;
    uint64_t gpa; // Guest Physical Address (for two-stage)
    int type;     // 0: Strong, 1: Device, 2: Normal
    int has_stage_two;
    uint32_t vmid;
} MmuEvent;

void update_mmu_event(MmuEvent *event);

// Exception callback
typedef struct {
    uint32_t mExceptionID;
    uint32_t mExceptionAttributes;
    const char* mpComments;
    uint64_t mEPC;
    uint64_t mtval2;
    uint64_t htval;
    uint64_t htinst;
    int is_guest_fault;
} SimException;

void update_exception_event(const SimException* exception);

#ifdef __cplusplus
}
#endif

#endif // FORCE_HANDCAR_COSIM_WRAPPER_H
