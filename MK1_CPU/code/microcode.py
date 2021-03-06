from copy import deepcopy
import argparse
from io import BytesIO
import sys
from functools import reduce

_VERSION = "2.0d"

HLT = 0b10000000000000000000000000000000  # Halt clock
STK = 0b01000000000000000000000000000000  # Memory Stack address space
PE  = 0b00100000000000000000000000000000  # Program counter enable
AI  = 0b00010000000000000000000000000000  # A register in
BI  = 0b00001000000000000000000000000000  # B register in
CI  = 0b00011000000000000000000000000000  # C register in
DI  = 0b00000100000000000000000000000000  # D register in
SI  = 0b00010100000000000000000000000000  # StakPointer register in
EI  = 0b00001100000000000000000000000000  # ALU register in
PI  = 0b00011100000000000000000000000000  # Program counter in
MI  = 0b00000010000000000000000000000000  # Memory address register in
RI  = 0b00000001000000000000000000000000  # RAM data in
II  = 0b00000000100000000000000000000000  # Instruction register in
OI  = 0b00000000010000000000000000000000  # Output register in
XI  = 0b00000000001000000000000000000000  # External Interface in
AO  = 0b00000000000100000000000000000000  # A register out
BO  = 0b00000000000010000000000000000000  # B register out
CO  = 0b00000000000110000000000000000000  # C register out
DO  = 0b00000000000001000000000000000000  # D register out
PO  = 0b00000000000101000000000000000000  # Program Counter out
SO  = 0b00000000000011000000000000000000  # StackPointer register out
EO  = 0b00000000000111000000000000000000  # ALU register out
RO  = 0b00000000000000100000000000000000  # RAM data out
_IO = 0b00000000000000010000000000000000  # Instruction register out
SUB = 0b00000000000000001000000000000000  # ALU subtract mode
OR  = 0b00000000000000000100000000000000  # ALU OR mode
AND = 0b00000000000000001100000000000000  # ALU AND mode
SHF = 0b00000000000000000010000000000000  # REG A SHIFT mode
ROT = 0b00000000000000001010000000000000  # REG A ROTATE mode
RGT = 0b00000000000000000000000000010000  # Right SHIFT or ROTATE
NOT = 0b00000000000000001110000000000000  # ALU NOT mode
FI  = 0b00000000000000000001000000000000  # Flags in
SU  = 0b00000000000000000000100000000000  # StackPointer count UP
SD  = 0b00000000000000000000010000000000  # StackPointer count DOWN
U0  = 0b00000000000000000000001000000000  # X-USR sig 0
U1  = 0b00000000000000000000000100000000  # X-USR sig 1
E0  = 0b00000000000000000000000010000000  # X-Enable 0
E1  = 0b00000000000000000000000001000000  # X-Enable 1
HL  = 0b00000000000000000000000000100000  # HL address mode
RST = 0b00000000000000000000000000000001  # Reset step counter

signals = {HLT : "HLT", STK: "STK", PE: "PE" , AI: "AI", BI: "BI", CI: "CI", DI: "DI", SI: "SI", EI: "EI", PI: "PI", MI: "MI", RI: "RI", II: "II", OI: "OI", XI: "XI", AO: "AO", BO: "BO", CO: "CO", DO: "DO", PO: "PO", SO: "SO", EO: "EO", RO: "RO", _IO: "IO", SUB: "SUB", OR: "OR", AND: "AND", SHF: "SHF", ROT: "SHF", RGT: "RGT", NOT: "NOT", FI: "FI", SU: "SU", SD: "SD", U0: "U0", U1: "U1", E0: "E0", E1: "E1", HL: "HL", RST: "RST"}

register_map = {0: ('$a', AI, AO),
                1: ('$b', BI, BO),
                2: ('$c', CI, CO),
                3: ('$d', DI, DO),
                4: ('$sp', SI, SO),
                5: ('$pc', PI, PO),
                6: ('$out', OI, 0),
                7: ('imm', 0, RO)}

alu_op_map = {0: ('add', 0), 1: ('sub', SUB), 2: ('or', OR), 3: ('and', AND)}

ucode_template = dict()

#MOV
#move $a $b
#nop = move $a $a
#jmp = move imm $pc
#--- specials ---
#exw 0 0 = move $a imm
#exw 0 1 = move $b imm
#exw 1 0 = move $c imm
#exw 1 1 = move $d imm
#je0 = move $sp imm
#je1 = move $pc imm
#jcf = move $spp imm
#jzf = move $imm imm
ucode_template.update({
    (0b00 << 6) + (first << 3) + second : ('move %s, %s'%(register_map[first][0], register_map[second][0]), [MI|PO, RO|II|PE, register_map[first][2]|register_map[second][1], RST, RST, RST, RST, RST] if first != 7 else
    [MI|PO, RO|II|PE, PO|MI, PE|register_map[first][2]|register_map[second][1], RST, RST, RST, RST], (second == 7 or first == 7))
    for first in range(8) for second in range(8)})

#LOAD
#loadi $a imm
#load $a [$b]
#pop $a = load $a [$spp]
#ret = load $pc [$spp]
#-- specials --
#exr 0 = load imm $a
#exr 1 = load imm $b
# 3: ('not', NOT), 4: ('sll', SHF), 5: ('srl', SHF|RGT), 6: ('rll', ROT), 7: ('rlr', ROT|RGT)
#not = load imm $c
#sll = load imm $d
#srl = load imm $sp
#rll = load imm $pc
#rlr = load imm $spp
#out = load imm imm

#6: ('$spp', SO|SD, SO|SU)
ucode_template.update({
    (0b01 << 6) + (first << 3) + second : ('load %s, [%s]'%(register_map[first][0], register_map[second][0]),
    [MI|PO, RO|II|PE, SU,register_map[second][2]|MI, STK|register_map[first][1]|RO, (PE if first == 5 else RST), RST, RST] if second == 4 else
    [MI|PO, RO|II|PE, register_map[second][2]|MI, HL|register_map[first][1]|RO, RST, RST, RST, RST], (second == 7 or first == 7))
    for first in range(7) for second in range(7)})

ucode_template.update({
    (0b01 << 6) + (first << 3) + second : ('load %s, [%s]'%(register_map[first][0], register_map[second][0]),
    [MI|PO, RO|II|PE, PO|MI|SU,PE|register_map[second][2]|MI, STK|register_map[first][1]|RO, (PE if first == 5 else RST), RST, RST] if second == 4 else
    [MI|PO, RO|II|PE, PO|MI, PE|register_map[second][2]|MI, HL|register_map[first][1]|RO, RST, RST, RST], (second == 7 or first == 7))
    for first in range(7) for second in range(7,8)})

#STORE
#store $a imm
#store $a [$b]
#push $a = store $a [$spp]
#jal imm = stor $pc, $spp
#-- specials --
#op_i x $b = 10 - 11 - op - $b -> immediate operation on $a, result on $b
#hlt = store $a [$sp]

#6: ('$spp', SO|SD, SO|SU)
ucode_template.update({
    (0b10 << 6) + (first << 3) + second : ('stor %s, [%s]'%(register_map[first][0], register_map[second][0]), [MI|PO, RO|II|PE, register_map[second][2]|MI, (STK|SD if second == 4 else HL)|register_map[first][2]|RI, RST, RST, RST, RST], (second == 7 or first == 7))
    for first in range(6) for second in range(7)})

ucode_template.update({
    (0b10 << 6) + (first << 3) + second : ('stor %s, [%s]'%(register_map[first][0], register_map[second][0]), [MI|PO, RO|II|PE, PO|MI, PE|register_map[second][2]|MI, (STK|SD if second == 4 else HL)|register_map[first][2]|RI, RST, RST, RST], (second == 7 or first == 7))
    for first in range(6) for second in range(7,8)})

ucode_template.update({
    (0b1011 << 4) + (op << 2) + second : ('%s imm, %s'%(alu_op_map[op][0], register_map[second][0]), [MI|PO, RO|II|PE,  PO|MI,  PE|RO|EI, register_map[second][1]|EO|FI|alu_op_map[op][1], RST, RST, RST], True)
    for second in range(4) for op in range(4)})

ucode_template[0b01111111] = ('hlt', [MI|PO, RO|II|PE,  HLT, RST, RST, RST, RST, RST], False)
#ALU
#op $a $b
#11 - op - rs - rd
ucode_template.update({
    (0b11 << 6) + (op << 4) + (first << 2) + second : ('%s %s, %s'%(alu_op_map[op][0], register_map[first][0], register_map[second][0]), [MI|PO, RO|II|PE, register_map[first][2]|EI, register_map[second][1]|EO|FI|alu_op_map[op][1], RST, RST, RST, RST], False)
    for first in range(4) for second in range(4) for op in range(4)})

ucode_template[0b01111000] = ('exr 0', [MI|PO, RO|II|PE, XI|E0|AI, RST, RST, RST, RST, RST], False)
ucode_template[0b01111001] = ('exr 1', [MI|PO, RO|II|PE, XI|E1|AI,  RST, RST, RST, RST, RST], False)

ucode_template[0b01111010] = ('not', [MI|PO, RO|II|PE,  AO|EI, AI, NOT|EO|AI, RST, RST, RST], False)
ucode_template[0b01111011] = ('sll', [MI|PO, RO|II|PE,  SHF|AI, RST,     RST, RST, RST, RST], False)
ucode_template[0b01111100] = ('slr', [MI|PO, RO|II|PE,  SHF|RGT|AI, RST, RST, RST, RST, RST], False)
ucode_template[0b01111101] = ('rll', [MI|PO, RO|II|PE,  ROT|AI, RST,     RST, RST, RST, RST], False)
ucode_template[0b01111110] = ('rlr', [MI|PO, RO|II|PE,  ROT|RGT|AI, RST, RST, RST, RST, RST], False)

ucode_template[0b00000111] = ('exw 0 0', [MI|PO, RO|II|PE, AO|E0, RST, RST, RST, RST, RST], False)
ucode_template[0b00001111] = ('exw 0 1', [MI|PO, RO|II|PE, AO|E0|U0, RST, RST, RST, RST, RST], False)
ucode_template[0b10001110] = ('exw 0 2', [MI|PO, RO|II|PE, AO|E0|U1, RST, RST, RST, RST, RST], False)
ucode_template[0b10010110] = ('exw 0 3', [MI|PO, RO|II|PE, AO|E0|U1|U0, RST, RST, RST, RST, RST], False)
ucode_template[0b00010111] = ('exw 1 0', [MI|PO, RO|II|PE, AO|E1, RST, RST, RST, RST, RST], False)
ucode_template[0b00011111] = ('exw 1 1', [MI|PO, RO|II|PE, AO|E1|U0, RST, RST, RST, RST, RST], False)
ucode_template[0b10011110] = ('exw 1 2', [MI|PO, RO|II|PE, AO|E1|U1, RST, RST, RST, RST, RST], False)
ucode_template[0b10100110] = ('exw 1 3', [MI|PO, RO|II|PE, AO|E1|U1|U0, RST, RST, RST, RST, RST], False)

ucode_template[0b10101110] = ('cmp $b', [MI|PO, RO|II|PE, BO|EI, SUB|FI, RST, RST, RST, RST], False)
ucode_template[0b01000110] = ('cmp $c', [MI|PO, RO|II|PE, CO|EI, SUB|FI, RST, RST, RST, RST], False)
ucode_template[0b01001110] = ('cmp $d', [MI|PO, RO|II|PE, DO|EI, SUB|FI, RST, RST, RST, RST], False)
ucode_template[0b10000110] = ('cmp imm', [MI|PO, RO|II|PE,  PO|MI, PE|RO|EI, SUB|FI, RST, RST, RST], False)

ucode_template[0b00100111] = ('je0', [MI|PO, RO|II|PE, PE, RST, RST, RST, RST, RST], False)
ucode_template[0b00101111] = ('je1', [MI|PO, RO|II|PE, PE, RST, RST, RST, RST, RST], False)
ucode_template[0b00110111] = ('jcf', [MI|PO, RO|II|PE, PE, RST, RST, RST, RST, RST], False)
ucode_template[0b00111111] = ('jzf', [MI|PO, RO|II|PE, PE, RST, RST, RST, RST, RST], False)

def checkUCode():
    for op, code in ucode_template.items():
        if len(code) < 3 or len(code[1]) != 8:
            print("Error:", str(op), len(code), len(code[1]))

instruction_decode = {y[0]:x for x,y in ucode_template.items()}

#TODO
ucode_template[instruction_decode['stor $pc, [$sp]']][1][4:6] = [PO|MI, RO|register_map[5][1]]

ucode = list(range(16)) #flag instruction step
def initUCode():

    FLAGS_IRQ00IRQ10Z0C0 = 0
    FLAGS_IRQ00IRQ10Z0C1 = 1
    FLAGS_IRQ00IRQ10Z1C0 = 2
    FLAGS_IRQ00IRQ10Z1C1 = 3
    FLAGS_IRQ01IRQ10Z0C0 = 4
    FLAGS_IRQ01IRQ10Z0C1 = 5
    FLAGS_IRQ01IRQ10Z1C0 = 6
    FLAGS_IRQ01IRQ10Z1C1 = 7
    FLAGS_IRQ00IRQ11Z0C0 = 8
    FLAGS_IRQ00IRQ11Z0C1 = 9
    FLAGS_IRQ00IRQ11Z1C0 = 10
    FLAGS_IRQ00IRQ11Z1C1 = 11
    FLAGS_IRQ01IRQ11Z0C0 = 12
    FLAGS_IRQ01IRQ11Z0C1 = 13
    FLAGS_IRQ01IRQ11Z1C0 = 14
    FLAGS_IRQ01IRQ11Z1C1 = 15

    #print(instruction_decode.keys())

    J0 = instruction_decode['je0']#je0 = move $sp imm
    J1 = instruction_decode['je1']#je1 = move $pc imm
    JC = instruction_decode['jcf']#jcf = move $spp imm
    JZ = instruction_decode['jzf']#jzf = move $imm imm

    #ZF = 0, CF = 0, IRQ0 = 0, IRQ1 = 0
    ucode[FLAGS_IRQ00IRQ10Z0C0] = deepcopy(ucode_template)

    #ZF = 0, CF = 0, IRQ0 = 0, IRQ1 = 1
    ucode[FLAGS_IRQ00IRQ11Z0C0] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ00IRQ11Z0C0][J1][1][2:4] = [PO|MI, RO|PI];

    #ZF = 0, CF = 0, IRQ0 = 1, IRQ1 = 0
    ucode[FLAGS_IRQ01IRQ10Z0C0] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ01IRQ10Z0C0][J0][1][2:4] = [PO|MI, RO|PI];

    #ZF = 0, CF = 0, IRQ0 = 1, IRQ1 = 1
    ucode[FLAGS_IRQ01IRQ11Z0C0] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ01IRQ11Z0C0][J0][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ11Z0C0][J1][1][2:4] = [PO|MI, RO|PI];

    #ZF = 0, CF = 1, IRQ0 = 0, IRQ1 = 0
    ucode[FLAGS_IRQ00IRQ10Z0C1] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ00IRQ10Z0C1][JC][1][2:4] = [PO|MI, RO|PI];

    #ZF = 0, CF = 1, IRQ0 = 0, IRQ1 = 1
    ucode[FLAGS_IRQ00IRQ11Z0C1] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ00IRQ11Z0C1][JC][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ00IRQ11Z0C1][J1][1][2:4] = [PO|MI, RO|PI];

    #ZF = 0, CF = 1, IRQ0 = 1, IRQ1 = 0
    ucode[FLAGS_IRQ01IRQ10Z0C1] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ01IRQ10Z0C1][JC][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ10Z0C1][J0][1][2:4] = [PO|MI, RO|PI];

    #ZF = 0, CF = 1, IRQ0 = 1, IRQ1 = 1
    ucode[FLAGS_IRQ01IRQ11Z0C1] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ01IRQ11Z0C1][JC][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ11Z0C1][J0][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ11Z0C1][J1][1][2:4] = [PO|MI, RO|PI];

    #ZF = 1, CF = 0, IRQ0 = 0, IRQ1 = 0
    ucode[FLAGS_IRQ00IRQ10Z1C0] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ00IRQ10Z1C0][JZ][1][2:4] = [PO|MI, RO|PI];

    #ZF = 1, CF = 0, IRQ0 = 0, IRQ1 = 1
    ucode[FLAGS_IRQ00IRQ11Z1C0] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ00IRQ11Z1C0][JZ][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ00IRQ11Z1C0][J1][1][2:4] = [PO|MI, RO|PI];

    #ZF = 1, CF = 0, IRQ0 = 1, IRQ1 = 0
    ucode[FLAGS_IRQ01IRQ10Z1C0] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ01IRQ10Z1C0][JZ][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ10Z1C0][J0][1][2:4] = [PO|MI, RO|PI];

    #ZF = 1, CF = 0, IRQ0 = 1, IRQ1 = 1
    ucode[FLAGS_IRQ01IRQ11Z1C0] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ01IRQ11Z1C0][JZ][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ11Z1C0][J0][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ11Z1C0][J1][1][2:4] = [PO|MI, RO|PI];

    #ZF = 1, CF = 1, IRQ0 = 0, IRQ1 = 0
    ucode[FLAGS_IRQ00IRQ10Z1C1] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ00IRQ10Z1C1][JC][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ00IRQ10Z1C1][JZ][1][2:4] = [PO|MI, RO|PI];

    #ZF = 1, CF = 1, IRQ0 = 0, IRQ1 = 1
    ucode[FLAGS_IRQ00IRQ11Z1C1] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ00IRQ11Z1C1][JC][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ00IRQ11Z1C1][JZ][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ00IRQ11Z1C1][J1][1][2:4] = [PO|MI, RO|PI];

    #ZF = 1, CF = 1, IRQ0 = 1, IRQ1 = 0
    ucode[FLAGS_IRQ01IRQ10Z1C1] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ01IRQ10Z1C1][JC][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ10Z1C1][JZ][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ10Z1C1][J0][1][2:4] = [PO|MI, RO|PI];

    #ZF = 1, CF = 1, IRQ0 = 1, IRQ1 = 1
    ucode[FLAGS_IRQ01IRQ11Z1C1] =  deepcopy(ucode_template)
    ucode[FLAGS_IRQ01IRQ11Z1C1][JC][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ11Z1C1][JZ][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ11Z1C1][J0][1][2:4] = [PO|MI, RO|PI];
    ucode[FLAGS_IRQ01IRQ11Z1C1][J1][1][2:4] = [PO|MI, RO|PI];


checkUCode()
initUCode()

def byte(value):
    return (value).to_bytes(1, 'big', signed=False)

def write(address, data, out):
    out.seek(address)
    data = data & 255
    out.write(data.to_bytes(1, 'big'))

def generate_microcode():
    #Program data bytes
    print("Generating microcode...")

    with open("microcode.bin", 'wb') as out:
        #Program the 8 high-order bits of microcode into the first 128 bytes of EEPROM
        for address in range(131072):
            flags       = (address & 0b00111100000000000) >> 11
            byte_sel    = (address & 0b11000000000000000) >> 15
            instruction = (address & 0b00000011111111000) >> 3
            step        = (address & 0b00000000000000111)

            if instruction not in ucode_template or len(ucode[flags][instruction][1]) == 0:
                print ("unused op-code: $s"%bin(instruction))
                instruction = instruction_decode['move $a, $a']

            if byte_sel == 0:
                write(address, ucode[flags][instruction][1][step] >> 24, out)
            elif byte_sel == 1:
                write(address, ucode[flags][instruction][1][step] >> 16, out)
            elif byte_sel == 2:
                write(address, ucode[flags][instruction][1][step] >> 8, out)
            elif byte_sel == 3:
                write(address, ucode[flags][instruction][1][step] >> 0, out)
            else:
                write(address, 0, out)

        def get_checked_signals(k, i):
            return [sorted_signals[x] for x in range(i) if k & sorted_signals[x] == sorted_signals[x] and reduce(lambda a, b: a | b, sorted_signals[:x], 0) != k]

        with open("microcode.txt", 'w') as out:
            sorted_signals = sorted(signals.keys(), reverse=True, key=lambda x: (int(bin(x).replace('0b', '').replace('0', ' ').strip().replace(' ', '0')), -1 if any([x & i == x for i in signals.keys() if i != x]) else 1))
            for mnemonic, opcode in sorted(instruction_decode.items()):
                print(mnemonic, format(opcode, '08b'), "[" + ',\t'.join(['|'.join([signals[y] for i, y in enumerate(sorted_signals) if x & y == y and x & reduce(lambda a, b: a | b, get_checked_signals(x, i), 0) != x]) for x in ucode_template[opcode][1]]) + "]", sep='\t', file=out)

        print("done")

def assemble_binary(input_file):
    address_table = dict()
    b = bytes()
    buffer = BytesIO(b)
    written_bytes = 0
    with open(input_file, 'r') as f:
        address = 0
        line_num = 0
        for line in f:
            line_num += 1
            if ";" in line:
                line = line[:line.find(';')]
            line = line.strip()
            if len(line) == 0 or line.startswith(";"):
                continue
            components = line.split(" ")
            curr_address = address
            if ":" in line:
                components = line.split(":")
                value = components[0].strip()
                if value.isnumeric():
                    curr_address = int(value)*2
                else:
                    if value in address_table:
                        #print(value, address_table[value])
                        for location in address_table[value]:
                            buffer.seek(location)
                            buffer.write(byte(curr_address // 2))
                    address_table[value] = curr_address // 2
                    if len(components[1].strip()) == 0:
                        continue
                    address += 2
                components = components[1].strip().split(" ")
            else:
                address += 2
            mnemonic_value = components[0].strip()
            if mnemonic_value == ".data":
                buffer.seek(curr_address)
                data = components[1:]
                for value in data:
                    written_bytes += buffer.write(byte(int(value.strip())))
                    written_bytes += buffer.write(byte(0))
                    address += 2
                continue

            if not mnemonic_value.isnumeric() and mnemonic_value not in instruction_decode:
                print("Error @ line %d: instruction not recognized: '%s'"%(line_num, mnemonic_value))
                sys.exit(1)
            instruction = int(mnemonic_value) if mnemonic_value.isnumeric() else instruction_decode[mnemonic_value]
            if not mnemonic_value.isnumeric() and len(components) == 1 and ucode_template[instruction][2]:
                print("Error @ line [%d] %s : missing parameter for instruction: %s" % (line_num, line, mnemonic_value))
                sys.exit(1)
            elif not mnemonic_value.isnumeric() and len(components) > 1 and not ucode_template[instruction][2]:
                print("Warning @ line [%d] %s : unused parameter for instruction '%s': %s" % (line_num, line, mnemonic_value, components[1]))
            value = components[1].strip() if len(components) > 1 else '0'
            if not value.isnumeric():
                if value in address_table and type(address_table[value]) is not list:
                    value = address_table[value]
                else:
                    if not value in address_table:
                        address_table[value] = list()
                    address_table[value].append(curr_address+1)
                    value = '0'
            argument = byte(int(value))
            buffer.seek(curr_address)
            written_bytes += buffer.write(byte(instruction))
            written_bytes += buffer.write(argument)

    if any([type(x) is list for x in address_table.values()]):
        print("Linking error")
        print([x for x,y in address_table.items() if type(y) is list])
        sys.exit(1)
    print("Used %d bytes (%.1f%%) out of 512 bytes."%(written_bytes, (written_bytes/512*100)))
    return buffer.getvalue()

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Assembler for MK1 computer.')
    parser.add_argument('-i', '--input', metavar='input', type=str,
                        help='input file name')
    parser.add_argument('-o', '--output', metavar='output', type=str,
                        help='output binary file name')

    args = parser.parse_args()

    if not args.input:
        generate_microcode()
        sys.exit(0)

    binary = assemble_binary(args.input)

    out_file_name = args.output or args.input[:args.input.rfind('.')]+".bin"

    with open(out_file_name, 'wb') as out:
        out.write(binary)

    print("%s generated (%d bytes)."%(out_file_name, len(binary)))
