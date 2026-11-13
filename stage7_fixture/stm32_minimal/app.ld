ENTRY(Reset_Handler)

MEMORY
{
    FLASH (rx) : ORIGIN = 0x08002000, LENGTH = 55K
}

SECTIONS
{
    .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
    .text : { *(.text*) *(.rodata*) } > FLASH
    /DISCARD/ : { *(.comment*) *(.note*) *(.ARM.attributes*) }
}
