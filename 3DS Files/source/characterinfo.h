// characterinfo -- retail's CharacterInfo.obj: the drivers' characters and
// body types, GLOBALB's 0x34300 and 0x34301.
//
// LoaderCharacterInfo (0x001d9330) is the chunk loader's slot 22. It points
// two tables into the bundle where they lie and counts their records; the
// rest looks them up by name, by name hash or by index. The frontend
// database copies a character into each player's FrontendPlayerInfo
// (fred.h), and AddDriverInfo hands the race a pointer to one.

#ifndef CHARACTERINFO_H
#define CHARACTERINFO_H

#include <stddef.h>
#include <stdint.h>

#define CHARACTER_INFO_CHUNK  0x00034300u
#define BODY_TYPE_INFO_CHUNK  0x00034301u

// CharacterInfo, 68 bytes (the demo's type is the same): which character,
// and the body type and the two skins it wears. GLOBALB has ten.
typedef struct CharacterInfo {
    int32_t CharacterNumber;                     //  0
    char    CharacterName[32];                   //  4
    char    BodyTypeName[24];                    // 36
    int32_t BodySkinNumber;                      // 60
    int32_t HeadSkinNumber;                      // 64
} CharacterInfo;                                 // 68

typedef char characterinfo_layout_check[
    (offsetof(CharacterInfo, CharacterName) == 4
     && offsetof(CharacterInfo, BodyTypeName) == 36
     && offsetof(CharacterInfo, HeadSkinNumber) == 64
     && sizeof(CharacterInfo) == 68) ? 1 : -1];

// BodyTypeInfo, 180 bytes: a body's three model names and its skins, as
// hashes. GLOBALB has four.
typedef struct BodyTypeInfo {
    char     BodyTypeName[24];                   //   0
    uint32_t ObjectNameHashA;                    //  24
    uint32_t ObjectNameHashB;                    //  28
    uint32_t ObjectNameHashC;                    //  32
    uint32_t MappedBodyHash;                     //  36
    uint32_t MappedHeadHash;                     //  40
    uint32_t NumBodyHash;                        //  44
    uint32_t NumHeadHash;                        //  48
    uint32_t BodySkinHash[16];                   //  52
    uint32_t HeadSkinHash[16];                   // 116
} BodyTypeInfo;                                  // 180

typedef char bodytypeinfo_layout_check[
    (offsetof(BodyTypeInfo, BodySkinHash) == 52
     && offsetof(BodyTypeInfo, HeadSkinHash) == 116
     && sizeof(BodyTypeInfo) == 180) ? 1 : -1];

// gp-17700 .. gp-17688, zero on the disc.
extern BodyTypeInfo  *pBodyTypeInfo;
extern int32_t        NumBodyTypeInfo;
extern CharacterInfo *pCharacterInfo;
extern int32_t        NumCharacterInfo;

// 0x001d9330. 0x34301: the body types start at the payload, size / 180 of
// them; 0x34300: the characters, size / 68. Either answers 1, anything
// else 0. The division is unsigned.
int loader_character_info(uint8_t *chunk);

// 0x001d93b0. The same two ids clear their pointer and count and answer 1.
int unloader_character_info(uint8_t *chunk);

// 0x001d93f8, GetBodyTypeInfo(char*): the first body whose name bStrICmp
// matches, or NULL.
BodyTypeInfo *get_body_type_info(const char *name);

// 0x001d9480, GetCharacterInfo(char*): the first character whose name
// matches, by bStrICmp, or NULL.
CharacterInfo *get_character_info_by_name(const char *name);

// 0x001d9508: the first character whose name's bStringHash is `hash`.
CharacterInfo *get_character_info_from_name_hash(uint32_t hash);

// 0x001d9588.
int32_t get_num_character_infos(void);

// 0x001d9590, GetCharacterInfo(int): NULL outside 0 .. NumCharacterInfo-1.
CharacterInfo *get_character_info(int32_t i);

#endif
