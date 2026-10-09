// nisinfo -- the NIS table: LoaderNisInfo, slot 20 of the LoaderTable
// (retail 0x001b3358, and UnloaderNisInfo at 0x001b33a0), and the three
// lookups the players and the NisManager make in it (0x001b3490 ..
// 0x001b3688).
//
// GLOBALB.BUN carries the one chunk, 0x00037010: eight NisInfo records of
// 160 bytes each, the three arrests (NIS_Arrest01..03) and the five
// tickets (NIS_Ticket01..04 and 06), each with its frame count and how
// many cameras its .CAM file has. The loader keeps the chunk's data where
// the bundle has it -- eight bytes in, no rounding up -- and the count,
// size / 160. Nothing else in the chunk is read here.
//
// See docs/formats/nis.md; tools/nis_check.py runs these against retail.

#ifndef NISINFO_H
#define NISINFO_H

#include <stdint.h>

#define NIS_INFO_CHUNK_ID 0x00037010u

// NisType: what a NIS shows. The table's Type words are 1 and 2.
#define NIS_TYPE_TICKET 1
#define NIS_TYPE_ARREST 2

// NisInfo, 160 bytes (.mdebug type#3347), as it sits in the bundle. The
// two animations are name hashes; so are the body types, by the look of
// them.
typedef struct NisInfo {
    char      Name[32];                     //   0  "NIS_Ticket01"
    int32_t   Type;                         //  32  NIS_TYPE_*
    int32_t   ApplyDriverOffsets;           //  36
    int32_t   NisNumber;                    //  40  its index in the table
    int32_t   NumFrames;                    //  44  at 30 a second
    int32_t   NumCameras;                   //  48
    uint32_t  PlayerAnimation;              //  52
    uint32_t  OtherAnimation;               //  56
    int32_t   Pad1;                         //  60
    int32_t   NumAllowablePlayerBodyTypes;  //  64
    int32_t   NumAllowableOtherBodyTypes;   //  68
    int32_t   Pad2;                         //  72
    int32_t   Pad3;                         //  76
    uint32_t  PlayerProps[2];               //  80
    uint32_t  OtherProps[2];                //  88
    uint32_t  AllowablePlayerBodyTypes[8];  //  96
    uint32_t  AllowableOtherBodyTypes[8];   // 128
} NisInfo;

_Static_assert(sizeof(NisInfo) == 160, "NisInfo is 160 bytes");

// gp-18844 and gp-18848: the chunk's records and how many, or NULL and 0.
extern NisInfo *NisInfoTable;
extern int32_t  NumNisInfos;

// LoaderNisInfo (0x001b3358): a chunk of NIS_INFO_CHUNK_ID is the table,
// at chunk + 8, and its size over 160 (`divu`) the count; 1. Any other
// chunk, 0. UnloaderNisInfo (0x001b33a0) empties both for the one type.
int loader_nis_info(uint8_t *chunk);
int unloader_nis_info(uint8_t *chunk);

// GetNumNisInfo(NisType), 0x001b3490: how many of the records have that
// Type. 0 without a table.
int32_t get_num_nis_info(int32_t type);

// GetNisInfo(int), 0x001b3608: record n, or NULL without a table or when
// n is past the end -- a signed compare, so retail's test lets a negative
// n through, and the port does too.
NisInfo *get_nis_info(int32_t n);

// GetNisInfo(int, NisType), 0x001b3638: the n'th record of that Type,
// counting from 0, or NULL when there are not that many.
NisInfo *get_nis_info_by_type(int32_t n, int32_t type);

#endif
