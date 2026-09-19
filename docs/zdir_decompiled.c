// Decompiled out of PS2 Files/NFSHP2.ELF with Ghidra headless
// (tools/ghidra_scripts/DecompileByName.java). The ELF must be imported
// as MIPS:LE:64:64-32addr / o32 -- see HANDOFF.md session 3; the default
// MIPS:LE:32 cannot decode the EE's MIPS III sd/ld/daddu and truncates
// most of these functions to halt_baddata().

// ==== 0023b280 -> bStringHash__FPCc ====

int bStringHash__FPCc(byte *param_1)

{
  byte bVar1;
  int iVar2;
  
  iVar2 = -1;
  bVar1 = *param_1;
  while (bVar1 != 0) {
    bVar1 = *param_1;
    param_1 = param_1 + 1;
    iVar2 = iVar2 * 0x21 + (uint)bVar1;
    bVar1 = *param_1;
  }
  return iVar2;
}



// ==== 0023b2c0 -> bStringHash__FPCci ====

int bStringHash__FPCci(byte *param_1,int param_2)

{
  byte bVar1;
  
  bVar1 = *param_1;
  while (bVar1 != 0) {
    bVar1 = *param_1;
    param_1 = param_1 + 1;
    param_2 = param_2 * 0x21 + (uint)bVar1;
    bVar1 = *param_1;
  }
  return param_2;
}



// ==== 0023d608 -> LoadDirectory__Fii ====

/* WARNING: Control flow encountered bad instruction data */

void LoadDirectory__Fii(void)

{
                    /* WARNING: Bad instruction - Truncating control flow here */
  halt_baddata();
}



// ==== 0023d910 -> bLoadDirectoryFile__FPCcT0 ====

/* WARNING: Control flow encountered bad instruction data */

void bLoadDirectoryFile__FPCcT0(void)

{
                    /* WARNING: Bad instruction - Truncating control flow here */
  halt_baddata();
}



// ==== 0023daf8 -> bLoadDirectoryFile__FPCcT0i ====

/* WARNING: Control flow encountered bad instruction data */

void bLoadDirectoryFile__FPCcT0i(void)

{
                    /* WARNING: Bad instruction - Truncating control flow here */
  halt_baddata();
}





// ==== 00100830 -> LoaderTexturePack__FP6bChunk ====

/* WARNING: Removing unreachable block (ram,0x00100870) */
/* WARNING: Removing unreachable block (ram,0x00100954) */

undefined8 LoaderTexturePack__FP6bChunk(int *param_1)

{
  int iVar1;
  uint uVar2;
  int iVar3;
  int iVar4;
  undefined8 uVar5;
  uint uVar6;
  
  if (*param_1 == -0x4fcfffff) {
    iVar1 = param_1[3];
    uVar2 = *(uint *)((int)param_1 + iVar1 + 0x14);
    iVar4 = uVar2 + iVar1 + 0x10;
    iVar3 = *(int *)((int)param_1 + iVar4 + 0xc);
    uVar6 = (int)param_1 + iVar4 + 0x8f & 0xffffff80;
    uVar5 = bMalloc__FiPCcii(0x84,s_TexturePack_0028f140,0,0x10);
    uVar5 = __11TexturePackPCc(uVar5,param_1 + 4);
    param_1[8] = (int)uVar5;
    AttachTextureTable__11TexturePackP11TextureInfoi(uVar5,(int)param_1 + iVar1 + 0x18,uVar2 / 0xa4)
    ;
    AssignTextureData__11TexturePackPcii
              (uVar5,uVar6,0,iVar3 - (uVar6 - ((int)param_1 + iVar4 + 0x10)));
  }
  else {
    if (*param_1 != -0x4fcfff00) {
      return 0;
    }
    iVar1 = param_1[3];
    uVar2 = *(uint *)((int)param_1 + iVar1 + 0x14);
    if (param_1[4] == 1) {
      uVar5 = bMalloc__FiPCcii(0x18,s_TextureAnimPack_0028f150,0,0x10);
      uVar5 = gcc2_compiled_(uVar5,(int)param_1 + iVar1 + 0x18,(int)param_1 + uVar2 + iVar1 + 0x20,
                             uVar2 / 0x34);
      param_1[5] = (int)uVar5;
      InitAnims__15TextureAnimPack(uVar5);
      return 1;
    }
    param_1[5] = 0;
  }
  return 1;
}



// ==== 00102ff0 -> LoaderSolidList__FP6bChunk ====

/* WARNING: Control flow encountered bad instruction data */
/* WARNING: Removing unreachable block (ram,0x001031e0) */

undefined8 LoaderSolidList__FP6bChunk(int *param_1)

{
  int iVar1;
  undefined4 uVar2;
  undefined4 *puVar3;
  ushort uVar4;
  int iVar5;
  int iVar6;
  undefined8 uVar7;
  longlong lVar8;
  int iVar9;
  uint uVar10;
  int *piVar11;
  int *piVar12;
  undefined4 *puVar13;
  uint uVar14;
  longlong lVar15;
  undefined1 auStack_900 [2048];
  uint uStack_100;
  
  lVar15 = (longlong)(int)auStack_900;
  uVar7 = 0;
  if (*param_1 == -0x7ffcc000) {
    iVar9 = param_1[3];
    uStack_100 = (int)param_1 + param_1[1] + 8;
    bSPrintf__FPcPCce(lVar15,s_SolidList__s_0028fc90,param_1 + 4);
    iVar5 = bAddCodeineInventory__FPCcT0(lVar15,s__Enable__CodeineInventorySolids__0028fcb0);
    param_1[0x10] = iVar5;
    for (iVar9 = (int)param_1 + iVar9 + 8; uVar14 = iVar9 + 8, uVar14 < uStack_100;
        iVar9 = uVar14 + iVar9) {
      piVar12 = (int *)(iVar9 + 0x10);
      piVar11 = (int *)(uVar14 + *(int *)(iVar9 + 0xc) + 8);
      puVar13 = (undefined4 *)0x0;
      if (piVar12 != piVar11) {
        iVar5 = *piVar12;
        while( true ) {
          if (iVar5 == 0x34003) {
            uVar10 = piVar12[1];
            puVar13 = (undefined4 *)((int)piVar12 + 0x17U & 0xfffffff0);
          }
          else if (iVar5 == 0x34004) {
            uVar10 = piVar12[1];
            puVar13[0x2c] = (int)piVar12 + 0x17U & 0xfffffff0;
          }
          else if (iVar5 == 0x34006) {
            uVar10 = piVar12[1];
            puVar13[0x2e] = piVar12 + 2;
            *(short *)(puVar13 + 0x2b) = (short)(uVar10 >> 3);
          }
          else if (iVar5 == 0x3401d) {
            uVar10 = piVar12[1];
            puVar13[0x2f] = (int)piVar12 + 0x17U & 0xfffffff0;
          }
          else {
            if (iVar5 == 0x34005) {
              iVar9 = piVar12[1];
              uVar14 = (int)piVar12 + 0x17U & 0xfffffff0;
              puVar13[0x2d] = uVar14;
              puVar13[0xf] = iVar9 - (uVar14 - (int)(piVar12 + 2));
              ADDU.QB(lVar15,0x34006);
                    /* WARNING: Bad instruction - Truncating control flow here */
              halt_baddata();
            }
            if (iVar5 == 0x34007) {
              iVar5 = piVar12[1];
              uVar10 = (int)piVar12 + 0x17U & 0xfffffff0;
              puVar13[0x29] = uVar10;
              puVar13[0x28] = (iVar5 - (uVar10 - (int)(piVar12 + 2))) / 0x60;
              uVar10 = piVar12[1];
            }
            else if (iVar5 == 0x34012) {
              uVar10 = piVar12[1];
              puVar13[0x2a] = (int)piVar12 + 0x17U & 0xfffffff0;
            }
            else {
              uVar10 = piVar12[1];
              if (iVar5 == 0x34011) {
                *(int **)(puVar13[0x2a] + 8) = piVar12 + 2;
              }
            }
          }
          piVar12 = (int *)((int)piVar12 + uVar10 + 8);
          if (piVar12 == piVar11) break;
          iVar5 = *piVar12;
        }
      }
      FixTextureTable__6eSolid(puVar13);
      FixLightMaterialTable__6eSolid(puVar13);
      if (puVar13[10] == 0) {
        uVar4 = *(ushort *)(puVar13 + 0xc);
      }
      else {
        iVar5 = eFindSolid__FUi();
        if (iVar5 == 0) {
          uVar4 = *(ushort *)(puVar13 + 0xc);
        }
        else {
          puVar13[0x2a] = *(undefined4 *)(iVar5 + 0xa8);
          uVar4 = *(ushort *)(puVar13 + 0xc);
        }
      }
      if ((uVar4 & 0x10) == 0) {
LAB_00103318:
        iVar5 = eFindSolid__FUi(puVar13[2]);
        if (iVar5 == 0) {
          iVar9 = *(int *)(iVar9 + 0xc);
        }
        else {
          *(ushort *)(puVar13 + 0xc) = *(ushort *)(puVar13 + 0xc) | 2;
          *(ushort *)(iVar5 + 0x30) = *(ushort *)(iVar5 + 0x30) | 2;
          iVar9 = *(int *)(iVar9 + 0xc);
        }
      }
      else {
        lVar8 = eFindSolid__FUi(puVar13[2]);
        if (lVar8 == 0) {
          iVar5 = bOMalloc__FP8SlotPool(eVertexAnimatorSlotPool);
          *(undefined4 *)(iVar5 + 0xc) = 0;
          puVar13[0xb] = iVar5;
          *(undefined4 *)(iVar5 + 0xc) = 1;
          *(undefined4 *)(iVar5 + 8) = 0x1e;
          *(undefined4 **)(iVar5 + 0x10) = puVar13;
        }
        else {
          if ((*(ushort *)(puVar13 + 0xc) & 0x10) == 0) goto LAB_00103318;
          iVar6 = eFindSolid__FUi(puVar13[2]);
          iVar5 = *(int *)(iVar6 + 0x2c);
          iVar1 = *(int *)(iVar5 + 0xc);
          if (iVar1 < 0x40) {
            *(undefined4 **)(iVar5 + iVar1 * 4 + 0x10) = puVar13;
            *(int *)(iVar5 + 0xc) = iVar1 + 1;
            iVar5 = *(int *)(iVar6 + 0x2c);
          }
          uVar2 = *(undefined4 *)(iVar6 + 0xa8);
          puVar13[0xb] = iVar5;
          puVar13[0x2a] = uVar2;
        }
        if ((*(ushort *)(puVar13 + 0xc) & 0x10) == 0) goto LAB_00103318;
        iVar9 = *(int *)(iVar9 + 0xc);
      }
      puVar3 = DAT_00322784;
      eDirtySolids = 1;
      *DAT_00322784 = puVar13;
      DAT_00322784 = puVar13;
      *puVar13 = &SolidList;
      puVar13[1] = puVar3;
    }
    uVar7 = 1;
  }
  return uVar7;
}



// ==== 0013d890 -> LoaderFlailerChunk__FP6bChunk ====

undefined8 LoaderFlailerChunk__FP6bChunk(int *param_1)

{
  int iVar1;
  undefined4 *puVar2;
  int iVar3;
  undefined8 uVar4;
  int *piVar5;
  int *piVar6;
  int *piVar7;
  int *piVar8;
  int *piVar9;
  
  uVar4 = 0;
  if (*param_1 == -0x7ffefe00) {
    piVar8 = param_1 + 2;
    param_1 = (int *)((int)param_1 + param_1[1] + 8);
    piVar9 = (int *)0x0;
    if (piVar8 != param_1) {
      iVar3 = *piVar8;
      while( true ) {
        if (iVar3 == 0x10213) {
          piVar9 = piVar8 + 2;
          iVar1 = piVar8[1];
          *DAT_00323224 = (int)piVar9;
          piVar5 = piVar9;
          piVar8[3] = (int)DAT_00323224;
          DAT_00323224 = piVar5;
          piVar8[2] = (int)&FlailerProjectList;
          piVar8[5] = (int)(piVar8 + 5);
          piVar8[6] = (int)(piVar8 + 5);
        }
        else {
          iVar1 = piVar8[1];
          if (iVar3 == -0x7ffefdff) {
            piVar5 = piVar8 + 2;
            piVar7 = (int *)((int)piVar8 + iVar1 + 8);
            piVar6 = (int *)0x0;
            if (piVar5 != piVar7) {
              iVar3 = *piVar5;
              while( true ) {
                if (iVar3 == 0x10203) {
                  puVar2 = (undefined4 *)piVar9[4];
                  piVar6 = piVar5 + 2;
                  *(undefined2 *)((int)piVar5 + 0x26) = 1;
                  *puVar2 = piVar6;
                  piVar9[4] = (int)piVar6;
                  piVar5[3] = (int)puVar2;
                  piVar5[2] = (int)(piVar9 + 3);
                  piVar5[10] = (int)(piVar5 + 10);
                  piVar5[0xb] = (int)(piVar5 + 10);
                }
                else {
                  puVar2 = (undefined4 *)piVar6[9];
                  *puVar2 = piVar5 + 2;
                  piVar6[9] = (int)(piVar5 + 2);
                  piVar5[3] = (int)puVar2;
                  piVar5[2] = (int)(piVar6 + 8);
                }
                piVar5 = (int *)((int)piVar5 + piVar5[1] + 8);
                if (piVar5 == piVar7) break;
                iVar3 = *piVar5;
              }
            }
            if (piVar6 != (int *)0x0) {
              UpdateLanguageText__18FlailerScreenChunk(piVar6);
              iVar1 = piVar8[1];
            }
          }
        }
        piVar8 = (int *)((int)piVar8 + iVar1 + 8);
        if (piVar8 == param_1) break;
        iVar3 = *piVar8;
      }
    }
    uVar4 = 1;
  }
  return uVar4;
}



// ==== 0017fff8 -> LoaderCarInfo__FP6bChunk ====

undefined8 LoaderCarInfo__FP6bChunk(int *param_1)

{
  undefined8 uVar1;
  undefined8 uVar2;
  int iVar3;
  bool bVar4;
  int iVar5;
  int iVar6;
  undefined8 uStack_60;
  undefined8 uStack_58;
  undefined8 uStack_50;
  undefined8 uStack_48;
  undefined8 uStack_40;
  undefined8 uStack_38;
  
  if (*param_1 == 0x34600) {
    CarTypeInfoArray = (int)param_1 + 0x17U & 0xfffffff0;
    iVar6 = 0;
    do {
      uVar1 = GetAccelerationTable__F7CarType(iVar6);
      uVar2 = GetCarTypeInfo__F7CarType(iVar6);
      iVar6 = iVar6 + 1;
      MakeAccelerationTable__FP5TableP11CarTypeInfo(uVar1,uVar2);
    } while (iVar6 < 0x42);
    if (TheDemoDiscManager != 0) {
      uStack_60 = DAT_002976f0;
      uVar1 = uStack_60;
      uStack_58 = DAT_002976f8;
      uStack_50 = DAT_00297700;
      uStack_48 = DAT_00297708;
      uStack_40 = DAT_00297710;
      uStack_38 = DAT_00297718;
      uStack_60._0_4_ = (int)DAT_002976f0;
      iVar6 = (int)uStack_60;
      uStack_60 = uVar1;
      iVar3 = 0;
      do {
        bVar4 = false;
        if (iVar6 == iVar3) {
          bVar4 = true;
        }
        else {
          for (iVar6 = 1; iVar6 < 0xc; iVar6 = iVar6 + 1) {
            if (*(int *)((int)&uStack_60 + iVar6 * 4) == iVar3) {
              bVar4 = true;
              break;
            }
          }
        }
        iVar5 = iVar3 + 1;
        if (!bVar4) {
          iVar6 = GetCarTypeInfo__F7CarType(iVar3);
          *(undefined1 *)(iVar6 + 0x40) = 0;
        }
        iVar6 = (int)uStack_60;
        iVar3 = iVar5;
      } while (iVar5 < 0x42);
    }
    uVar1 = 1;
  }
  else {
    uVar1 = 0;
    if (*param_1 == 0x34601) {
      SkinInfoTable = param_1 + 2;
      NumSkinInfo = (uint)param_1[1] >> 6;
      uVar1 = 1;
    }
  }
  return uVar1;
}



// ==== 0018f6d8 -> TraverseChunks__FP6bChunkT0PPFP6bChunk_ii ====

void TraverseChunks__FP6bChunkT0PPFP6bChunk_ii(int param_1,int param_2,int param_3,int param_4)

{
  longlong lVar1;
  int iVar2;
  int iVar3;
  int iVar4;
  
  iVar4 = 0;
  iVar3 = 0;
  if (param_1 != param_2) {
    iVar2 = 0;
    do {
      lVar1 = (**(code **)(iVar2 + param_3))(param_1);
      if (lVar1 == 0) {
        iVar3 = iVar3 + 1;
        iVar4 = iVar4 + 1;
        if (iVar3 == param_4) {
          iVar3 = 0;
        }
        if (param_4 < iVar4) {
          bBreak__Fv();
          iVar2 = *(int *)(param_1 + 4);
          goto LAB_0018f75c;
        }
      }
      else {
        iVar2 = *(int *)(param_1 + 4);
        iVar4 = 0;
LAB_0018f75c:
        param_1 = param_1 + iVar2 + 8;
      }
      iVar2 = iVar3 << 2;
    } while (param_1 != param_2);
  }
  return;
}



// ==== 001a95f0 -> LoaderNisInfo__FP6bChunk ====

/* WARNING: Removing unreachable block (ram,0x001a961c) */

undefined8 LoaderNisInfo__FP6bChunk(int *param_1)

{
  if (*param_1 != 0x37010) {
    return 0;
  }
  NisInfoTable = param_1 + 2;
  NumNisInfos = (uint)param_1[1] / 0xa0;
  return 1;
}



// ==== 001aa460 -> LZDecompress__FPUcT0 ====

size_t LZDecompress__FPUcT0(int *param_1,byte *param_2)

{
  byte bVar1;
  byte *pbVar2;
  byte *__src;
  byte *pbVar3;
  byte *pbVar4;
  uint uVar5;
  int iVar6;
  uint uVar7;
  byte *pbVar8;
  size_t __n;
  
  if (((param_1 == (int *)0x0) || (param_2 == (byte *)0x0)) || (*param_1 != 0x504d4f43)) {
    __n = 0;
  }
  else {
    pbVar8 = (byte *)((int)param_1 + param_1[3]);
    __src = (byte *)(param_1 + 4);
    uVar7 = 1;
    pbVar4 = param_2;
    if (*(short *)((int)param_1 + 6) == 1) {
      __n = param_1[3] - 0x10;
      memcpy(param_2,__src,__n);
    }
    else {
      while (__src != pbVar8) {
        if (uVar7 == 1) {
          bVar1 = *__src;
          pbVar2 = __src + 1;
          __src = __src + 2;
          uVar7 = bVar1 | 0x10000 | (uint)*pbVar2 << 8;
        }
        iVar6 = 0xf;
        if (pbVar8 + -0x20 < __src) {
          iVar6 = 0;
        }
        for (; iVar6 != -1; iVar6 = iVar6 + -1) {
          if ((uVar7 & 1) == 0) {
            bVar1 = *__src;
            __src = __src + 1;
            *pbVar4 = bVar1;
            pbVar4 = pbVar4 + 1;
          }
          else {
            bVar1 = *__src;
            pbVar2 = __src + 1;
            __src = __src + 2;
            uVar5 = bVar1 & 0xf;
            pbVar2 = pbVar4 + -((bVar1 & 0xf0) << 4 | (uint)*pbVar2);
            *pbVar4 = *pbVar2;
            pbVar4[1] = pbVar2[1];
            pbVar3 = pbVar2 + 3;
            pbVar4[2] = pbVar2[2];
            pbVar4 = pbVar4 + 3;
            if ((bVar1 & 0xf) != 0) {
              do {
                bVar1 = *pbVar3;
                uVar5 = uVar5 - 1;
                pbVar3 = pbVar3 + 1;
                *pbVar4 = bVar1;
                pbVar4 = pbVar4 + 1;
              } while (uVar5 != 0);
            }
          }
          uVar7 = uVar7 >> 1;
        }
      }
      __n = (int)pbVar4 - (int)param_2;
    }
  }
  return __n;
}



// ==== 0020b040 -> LoaderLanguage__FP6bChunk ====

bool LoaderLanguage__FP6bChunk(undefined8 param_1)

{
  longlong lVar1;
  
  lVar1 = Loader__15LanguageManagerP6bChunk(TheLanguageManager,param_1);
  return lVar1 != 0;
}



// ==== 002217a8 -> BuildDecodeTab__7Huffman ====

void BuildDecodeTab__7Huffman(void)

{
  uint uVar1;
  int iVar2;
  uint uVar3;
  int iVar4;
  uint uVar5;
  int iVar6;
  uint uVar7;
  uint uVar8;
  
  uVar5 = 0;
  iVar6 = 1;
  do {
    uVar7 = 0;
    uVar8 = iVar6 + -1 >> 1;
    if (0 < iVar6) {
      do {
        uVar1 = uVar5 + (ushort)(&DAT_002a05da)[uVar5 * 2];
        uVar3 = (uint)(ushort)(&PrefixTab)[uVar5 * 2] << (uVar5 & 0x1f);
        if ((int)uVar1 < 10) {
          if (uVar5 == 0) {
            iVar2 = 0;
          }
          else {
            uVar3 = uVar3 | uVar7;
            if ((int)uVar7 < iVar6 / 2) {
              iVar2 = (uVar7 & uVar8) + (1 << (uVar5 - 1 & 0x1f));
            }
            else {
              iVar2 = -((uVar7 & uVar8) + (1 << (uVar5 - 1 & 0x1f)));
            }
          }
        }
        else {
          uVar3 = (int)uVar3 >> (uVar5 & 0x1f);
          iVar2 = -0x80;
          uVar1 = (uint)(ushort)(&DAT_002a05da)[uVar5 * 2];
        }
        iVar4 = 0;
        uVar7 = uVar7 + 1;
        do {
          if (iVar4 >> (9 - uVar1 & 0x1f) == uVar3) {
            if (iVar2 == -0x80) {
              (&DecodeTab)[iVar4 * 2] = (char)uVar5 + -1;
            }
            else {
              (&DecodeTab)[iVar4 * 2] = (char)uVar1;
            }
            *(char *)(iVar4 * 2 + 0x3279e9) = (char)iVar2;
          }
          iVar4 = iVar4 + 1;
        } while (iVar4 < 0x200);
      } while ((int)uVar7 < iVar6);
    }
    uVar5 = uVar5 + 1;
    iVar6 = 1 << (uVar5 & 0x1f);
  } while ((int)uVar5 < 0xc);
  return;
}



// ==== 00221928 -> Decompress__7HuffmanPsUi ====

void Decompress__7HuffmanPsUi(uint *param_1,short *param_2,int param_3)

{
  char cVar1;
  byte bVar2;
  ushort uVar3;
  bool bVar4;
  short sVar5;
  longlong lVar6;
  int iVar7;
  short *psVar8;
  int iVar9;
  uint uVar10;
  uint uVar11;
  uint uVar12;
  short *psVar13;
  short *psVar14;
  
  psVar14 = param_2 + param_3;
  if (param_2 < psVar14) {
    uVar11 = param_1[1];
    while( true ) {
      while (uVar11 < 0x19) {
        uVar10 = 0x18 - uVar11;
        uVar11 = uVar11 + 8;
        bVar2 = *(byte *)param_1[5];
        param_1[1] = uVar11;
        param_1[5] = (uint)((byte *)param_1[5] + 1);
        *param_1 = *param_1 | (uint)bVar2 << (uVar10 & 0x1f);
      }
      uVar10 = *param_1;
      iVar7 = (uVar10 >> 0x17) * 2;
      cVar1 = *(char *)(iVar7 + 0x3279e9);
      if (cVar1 == -0x80) {
        bVar2 = (&DecodeTab)[iVar7];
        uVar3 = (&DAT_002a05da)[(bVar2 + 1) * 2];
        *param_1 = uVar10 << (uVar3 & 0x1f);
        param_1[1] = uVar11 - uVar3;
        sVar5 = GETBITS__7HuffmanUi(param_1,1);
        uVar11 = *param_1;
        uVar10 = param_1[1];
        uVar12 = (uint)bVar2;
        *param_2 = (short)(uVar11 >> (-(uint)bVar2 & 0x1f)) + (short)(1 << (uVar12 & 0x1f));
        param_1[1] = uVar10 - uVar12;
        psVar13 = param_2 + 1;
        *param_1 = uVar11 << (uVar12 & 0x1f);
        if (sVar5 == 0) {
          bVar4 = psVar13 < psVar14;
        }
        else {
          bVar4 = psVar13 < psVar14;
          *param_2 = -*param_2;
        }
      }
      else if (cVar1 == '\0') {
        param_1[1] = uVar11 - 2;
        *param_1 = uVar10 << 2;
        lVar6 = GETBITS__7HuffmanUi(param_1,1);
        uVar11 = *param_1;
        if (lVar6 == 0) {
          *param_1 = uVar11 << 3;
          param_1[1] = param_1[1] - 3;
          iVar7 = (uVar11 >> 0x1d) + 1;
        }
        else {
          *param_1 = uVar11 << 6;
          param_1[1] = param_1[1] - 6;
          iVar7 = (uVar11 >> 0x1a) + 9;
        }
        iVar9 = -iVar7;
        psVar13 = param_2 + iVar7;
        bVar4 = psVar13 < psVar14;
        psVar8 = psVar13 + -iVar7;
        do {
          *psVar8 = 0;
          iVar9 = iVar9 + 1;
          psVar8 = psVar8 + 1;
        } while (iVar9 != 0);
      }
      else {
        *param_2 = (short)cVar1;
        psVar13 = param_2 + 1;
        bVar2 = (&DecodeTab)[iVar7];
        bVar4 = psVar13 < psVar14;
        *param_1 = uVar10 << (bVar2 & 0x1f);
        param_1[1] = uVar11 - bVar2;
      }
      if (!bVar4) break;
      uVar11 = param_1[1];
      param_2 = psVar13;
    }
  }
  return;
}



// ==== 0023d608 -> LoadDirectory__Fii ====

void LoadDirectory__Fii(longlong param_1,longlong param_2)

{
  int *piVar1;
  int iVar2;
  int iVar3;
  int *piVar4;
  int iVar5;
  undefined8 uVar6;
  undefined8 uVar7;
  int *piStack_90;
  undefined1 *puStack_8c;
  undefined1 auStack_80 [16];
  
  if (param_1 == 0) {
    bPrintf__FPCce(s_Loading_root_directory____002a2730);
  }
  else {
    bPrintf__FPCce(s_Loading_entire_directory____002a2710);
  }
  iVar5 = (int)param_2;
  if (param_2 == 0) {
    uVar6 = bMalloc__Fii(0x800,0x10);
    ReadSector__FPvii(uVar6,1,0xa6);
    iVar5 = ReadMemoryLong__FPCUc((int)uVar6 + 0x9e);
    uVar7 = ReadMemoryLong__FPCUc((int)uVar6 + 0xa6);
    bFree__FPv(uVar6);
  }
  else {
    uVar7 = 0x800;
  }
  EntireDirectoryLoaded = (undefined4)param_1;
  auStack_80[0] = 0;
  piStack_90 = (int *)&piStack_90;
  puStack_8c = (undefined1 *)&piStack_90;
  RecurseDirectory__FPt6bTList1Z18TempDirectoryEntryUiUiPCci
            (&piStack_90,iVar5 + 0x96,uVar7,auStack_80);
  if (DirectoryTable != 0) {
    bFree__FPv();
  }
  NumDirectoryEntries = TraversebList__5bListP5bNode(&piStack_90,0);
  DirectoryTable = bMalloc__FiPCcii(NumDirectoryEntries * 0xc,s_CD_Directory_002a2750,0,0x10);
  bPrintf__FPCce(s_CD_Directory___d_entries_002a2760,NumDirectoryEntries);
  if ((int **)piStack_90 != &piStack_90) {
    do {
      piVar4 = piStack_90;
      iVar5 = *piStack_90;
      piVar1 = (int *)piStack_90[1];
      iVar2 = piStack_90[2];
      *piVar1 = iVar5;
      *(int **)(iVar5 + 4) = piVar1;
      piStack_90[1] = 0xb;
      *piStack_90 = 0xb;
      uVar6 = bStringHash__FPCc(iVar2);
      iVar3 = DirectoryTable;
      iVar5 = piVar4[2];
      *(int *)(DirectoryTable + 0xc) = (int)uVar6;
      *(int *)(iVar3 + 0x10) = piVar4[3];
      iVar2 = piVar4[4];
      *(int *)(iVar3 + 0x14) = iVar2;
      bPrintf__FPCce(s_File___Hash__08X___Size__6d___s_002a2780,uVar6,iVar2,iVar5);
      piVar1 = piStack_90;
      while ((int **)piVar1 != &piStack_90) {
        iVar5 = bStringHash__FPCc(piVar1[2]);
        if (iVar5 == *(int *)(DirectoryTable + 0xc)) {
          bPrintf__FPCce(s_CD_FILENAME_HASH_COLLISION__Betw_002a27a8,piVar4[2],piVar1[2]);
          piVar1 = (int *)*piVar1;
        }
        else {
          piVar1 = (int *)*piVar1;
        }
      }
      if (piVar4 != (int *)0x0) {
        ___18TempDirectoryEntry(piVar4,3);
      }
    } while ((int **)piStack_90 != &piStack_90);
  }
  bPrintf__FPCce(s__d_files_002a27d8,NumDirectoryEntries);
  ___t6bTList1Z18TempDirectoryEntry(&piStack_90,2);
  return;
}



// ==== 0023d910 -> bLoadDirectoryFile__FPCcT0 ====

/* WARNING: Removing unreachable block (ram,0x0023da70) */

void bLoadDirectoryFile__FPCcT0(undefined8 param_1,undefined8 param_2)

{
  bool bVar1;
  int iVar2;
  int iVar3;
  longlong lVar4;
  undefined8 uVar5;
  uint uVar6;
  int iVar7;
  int iVar8;
  undefined1 auStack_190 [256];
  int aiStack_90 [12];
  uint auStack_60 [4];
  
  bPrintf__FPCce(s_bLoadDirectoryFile__s___s______002a2858,param_1,param_2);
  iVar8 = 0;
  auStack_60[0] = 0;
  lVar4 = bIsThereACDInTheDrive__Fv();
  if (lVar4 == 0) {
    iVar2 = bGetFile__FPCcPii(param_1,auStack_60,0x10);
  }
  else {
    bSPrintf__FPcPCce(auStack_190,s_cdrom___s_1_002a2878,param_1);
    lVar4 = sceOpen(auStack_190,1);
    if (lVar4 < 0) {
      bPrintf__FPCce(s_WARNING__sceOpen___could_not_fin_002a2888,auStack_190);
      return;
    }
    uVar5 = sceLseek(lVar4,0,2);
    auStack_60[0] = (uint)uVar5;
    iVar2 = bMalloc__FiPCcii(uVar5,param_1,0,0x10);
    sceLseek(lVar4,0,0);
    sceRead(lVar4,iVar2,auStack_60[0]);
    sceClose(lVar4);
    bSPrintf__FPcPCce(auStack_190,s___s_1_00324f38,param_2);
    lVar4 = sceCdSearchFile(aiStack_90,auStack_190);
    if (lVar4 == 0) {
      bPrintf__FPCce(s_WARNING__sceCdSearchFile___could_002a28b0,auStack_190);
    }
    else {
      iVar8 = aiStack_90[0] + 0x96;
    }
  }
  if (DirectoryTable != 0) {
    bFree__FPv(DirectoryTable);
  }
  uVar6 = auStack_60[0] / 0xc;
  iVar7 = 0;
  RealCDDirectoryLoaded = 1;
  EntireDirectoryLoaded = 1;
  DirectoryTable = iVar2;
  NumDirectoryEntries = uVar6;
  if (uVar6 != 0) {
    do {
      iVar7 = iVar7 + 1;
      bVar1 = iVar7 < (int)NumDirectoryEntries;
      iVar3 = uVar6 + iVar2;
      uVar6 = *(int *)(iVar3 + 4) + iVar8;
      *(uint *)(iVar3 + 4) = uVar6;
    } while (bVar1);
  }
  bPrintf__FPCce(s_num_files____d__data_fad____d_002a28e0,NumDirectoryEntries,iVar8);
  return;
}



