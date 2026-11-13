.syntax unified
.cpu cortex-m3
.thumb

/* The installed Bootloader jumps to the App vector table at 0x08002000. */
.section .isr_vector, "a", %progbits
.word 0x20005000
.word Reset_Handler + 1
.rept 14
.word Default_Handler + 1
.endr

.section .text.Reset_Handler, "ax", %progbits
.thumb_func
.global Reset_Handler
Reset_Handler:
    cpsid i
    ldr r0, =0x20000000
    ldr r2, =0xC7B70001
    str r2, [r0]
    movs r1, #0
    str r1, [r0, #4]

heartbeat_loop:
    ldr r3, =1000000
delay_loop:
    subs r3, r3, #1
    bne delay_loop
    adds r1, r1, #1
    str r1, [r0, #4]
    b heartbeat_loop

.thumb_func
Default_Handler:
    b Default_Handler
