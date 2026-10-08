#---------------------------------------------------------------------------------
.SUFFIXES:
#---------------------------------------------------------------------------------

# GNU Make's $(notdir ...)/$(dir ...)/etc. are whitespace-list based, so this
# Makefile (like all devkitPro templates) cannot be invoked from a path
# containing a space -- $(notdir $(CURDIR)) silently returns garbage and the
# top-level/recursive-build detection below breaks. If this project's path
# has a space in it (e.g. under "My Stuff"), build via tools/build_cia.sh
# (Windows: subst's a temporary space-free drive letter around the build) or
# `subst Z: "<path to 3DS Files>"` by hand, then run make from Z:\.
ifeq ($(strip $(DEVKITARM)),)
$(error "Please set DEVKITARM in your environment. export DEVKITARM=<path to>devkitARM")
endif

TOPDIR ?= $(CURDIR)
include $(DEVKITARM)/3ds_rules

#---------------------------------------------------------------------------------
# TARGET is the name of the output
# BUILD is the directory where object files & intermediate files will be placed
# SOURCES is a list of directories containing source code
# DATA is a list of directories containing data files
# INCLUDES is a list of directories containing header files
# ROMFS is the directory which contains the RomFS, relative to the Makefile
# APP_TITLE/APP_DESCRIPTION/APP_AUTHOR are stored in the SMDH file
#---------------------------------------------------------------------------------
TARGET		:=	NFSHP2-3DS
BUILD		:=	build
SOURCES		:=	source
DATA		:=	data
INCLUDES	:=	include
# No ROMFS -- the CIA/.3dsx is engine-only and ships with zero game data.
# Real game assets live in an external directory on the SD card, pointed to
# by nfshp2_config.txt at runtime (see source/main.c).
ROMFS		:=

APP_TITLE		:= NFSHP2 3DS
APP_DESCRIPTION	:= NFS Hot Pursuit 2 port skeleton
APP_AUTHOR		:= NFSHP2-3DS project

#---------------------------------------------------------------------------------
# options for code generation
#---------------------------------------------------------------------------------
ARCH	:=	-march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft

CFLAGS	:=	-g -Wall -O3 -mword-relocations \
			-ffunction-sections \
			$(ARCH)

CFLAGS	+=	$(INCLUDE) -D__3DS__

CXXFLAGS	:= $(CFLAGS) -fno-rtti -fno-exceptions -std=gnu++11

ASFLAGS	:=	-g $(ARCH)
# NOTE: do not raise the .3dsx stack with -Wl,--defsym,__stacksize__=... here.
# 3dsxtool reads that literal out of the pool as a relocation source and dies
# with "Relocation to invalid address!". The .3dsx keeps libctru's 32KB default;
# meta/app.rsf's StackSize covers the CIA. What actually keeps both safe is that
# the frontend loader chain no longer needs ~35KB of stack -- see texpack.c's
# s_active[] comment and loadFngScreen()'s scratch below.
LDFLAGS	=	-specs=3dsx.specs -g $(ARCH) -Wl,-Map,$(notdir $*.map) \
			$(C3DWRAP)

# citro3d's uniform upload, skipped when nothing changed, and its draws
# written in one go: see c3dwrap.c.
C3DWRAP	:=	-Wl,--wrap=C3D_UpdateUniforms \
			-Wl,--wrap=C3Di_LoadShaderUniforms \
			-Wl,--wrap=C3Di_DirtyUniforms \
			-Wl,--wrap=C3D_BindProgram \
			-Wl,--wrap=C3D_DrawElements \
			-Wl,--wrap=C3D_DrawArrays \
			-Wl,--wrap=GPUCMD_Add

LIBS	:= -lcitro2d -lcitro3d -lctru -lm

#---------------------------------------------------------------------------------
# list of directories containing libraries, this must be the top level containing
# include and lib
#---------------------------------------------------------------------------------
LIBDIRS	:= $(CTRULIB) $(PORTLIBS)

#---------------------------------------------------------------------------------
# no real need to edit anything past this point unless you need to add additional
# rules for different file extensions
#---------------------------------------------------------------------------------
ifneq ($(BUILD),$(notdir $(CURDIR)))
#---------------------------------------------------------------------------------

export OUTPUT	:=	$(CURDIR)/$(TARGET)
export TOPDIR	:=	$(CURDIR)

export VPATH	:=	$(foreach dir,$(SOURCES),$(CURDIR)/$(dir)) \
			$(foreach dir,$(DATA),$(CURDIR)/$(dir))

export DEPSDIR	:=	$(CURDIR)/$(BUILD)

CFILES		:=	$(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.c)))
CPPFILES	:=	$(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.cpp)))
SFILES		:=	$(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.s)))
BINFILES	:=	$(foreach dir,$(DATA),$(notdir $(wildcard $(dir)/*.*)))
# geolit.v.pica is linked into geosolid's shbin (see the shader rule).
PICAFILES	:=	$(filter-out geolit.v.pica,\
			$(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.v.pica))))

#---------------------------------------------------------------------------------
ifeq ($(strip $(CPPFILES)),)
#---------------------------------------------------------------------------------
	export LD	:=	$(CC)
#---------------------------------------------------------------------------------
else
#---------------------------------------------------------------------------------
	export LD	:=	$(CXX)
#---------------------------------------------------------------------------------
endif
#---------------------------------------------------------------------------------

export OFILES_SOURCES 	:=	$(CPPFILES:.cpp=.o) $(CFILES:.c=.o) $(SFILES:.s=.o)

export OFILES_BIN	:=	$(addsuffix .o,$(BINFILES)) $(PICAFILES:.v.pica=.shbin.o)

export OFILES := $(OFILES_BIN) $(OFILES_SOURCES)

export HFILES	:=	$(addsuffix .h,$(subst .,_,$(BINFILES))) $(PICAFILES:.v.pica=_shbin.h)

export INCLUDE	:=	$(foreach dir,$(INCLUDES),-I$(CURDIR)/$(dir)) \
			$(foreach dir,$(LIBDIRS),-I$(dir)/include) \
			-I$(CURDIR)/$(BUILD)

export LIBPATHS	:=	$(foreach dir,$(LIBDIRS),-L$(dir)/lib)

export _3DSXDEPS	:=	$(if $(NO_SMDH),,$(OUTPUT).smdh)

ifeq ($(strip $(ICON)),)
	icons := $(wildcard *.png)
	ifneq (,$(findstring $(TARGET).png,$(icons)))
		export APP_ICON := $(TOPDIR)/$(TARGET).png
	else
		ifneq (,$(findstring icon.png,$(icons)))
			export APP_ICON := $(TOPDIR)/icon.png
		endif
	endif
else
	export APP_ICON := $(TOPDIR)/$(ICON)
endif

ifeq ($(strip $(NO_SMDH)),)
	export _3DSXFLAGS += --smdh=$(CURDIR)/$(TARGET).smdh
endif

ifneq ($(ROMFS),)
	export _3DSXFLAGS += --romfs=$(CURDIR)/$(ROMFS)
endif

.PHONY: all clean cia

#---------------------------------------------------------------------------------
all: $(BUILD) $(DEPSDIR)
	@$(MAKE) --no-print-directory -C "$(BUILD)" -f "$(CURDIR)/Makefile"

$(BUILD):
	@mkdir -p "$@"

ifneq ($(DEPSDIR),$(BUILD))
$(DEPSDIR):
	@mkdir -p "$@"
endif

#---------------------------------------------------------------------------------
# CIA packaging. makerom/bannertool aren't in devkitPro's package repos, so
# prebuilt binaries live in tools/3ds-bin (see HANDOFF.md). Requires
# meta/banner.png, meta/icon.png, meta/silence.wav (bannertool) plus
# meta/app.rsf (makerom).
#---------------------------------------------------------------------------------
MAKEROM		:= $(TOPDIR)/../tools/3ds-bin/makerom.exe
BANNERTOOL	:= $(TOPDIR)/../tools/3ds-bin/bannertool.exe

cia: all
	@"$(BANNERTOOL)" makebanner -i meta/banner.png -a meta/silence.wav -o meta/banner.bnr
	@"$(BANNERTOOL)" makesmdh -s "$(APP_TITLE)" -l "$(APP_DESCRIPTION)" -p "$(APP_AUTHOR)" -i meta/icon.png -o meta/icon.icn
	@"$(MAKEROM)" -f cia -o "$(TARGET).cia" -DAPP_ENCRYPTED=false -target t \
		-elf "$(OUTPUT).elf" -icon meta/icon.icn -banner meta/banner.bnr \
		-rsf meta/app.rsf
	@echo built ... $(TARGET).cia

#---------------------------------------------------------------------------------
clean:
	@echo clean ...
	@rm -fr "$(BUILD)" "$(TARGET).3dsx" "$(OUTPUT).smdh" "$(TARGET).elf" "$(TARGET).cia" meta/banner.bnr meta/icon.icn

#---------------------------------------------------------------------------------
else
#---------------------------------------------------------------------------------
# main targets
#---------------------------------------------------------------------------------
$(OUTPUT).3dsx	:	$(OUTPUT).elf $(_3DSXDEPS)

$(OFILES_SOURCES) : $(HFILES)

$(OUTPUT).elf	:	$(OFILES)

#---------------------------------------------------------------------------------
# you need a rule like this for each extension you use as binary data
#---------------------------------------------------------------------------------
%.bin.o	%_bin.h :	%.bin
#---------------------------------------------------------------------------------
	@echo $(notdir $<)
	@$(bin2o)

#---------------------------------------------------------------------------------
# citro2d .bcfnt glyph atlas (see data/conduit.bcfnt, generated from the
# user-supplied Conduit ITC Medium Italic.otf via devkitPro's mkbcfnt).
#---------------------------------------------------------------------------------
%.bcfnt.o	%_bcfnt.h :	%.bcfnt
#---------------------------------------------------------------------------------
	@echo $(notdir $<)
	@$(bin2o)

#---------------------------------------------------------------------------------
# PICA200 shader compilation (picasso + bin2s), same pattern as devkitPro's
# own citro3d examples (graphics/gpu/*/Makefile) -- .v.pica compiles straight
# to .shbin.o + _shbin.h in one step, skipping an intermediate .shbin Make
# target (which conflicts with 3ds_rules' own %.shbin pattern rule and
# produces a bogus "circular dependency" from make).
#---------------------------------------------------------------------------------
define shader-as
	$(eval CURBIN := $*.shbin)
	echo "$(CURBIN).o: $< $1" > $(DEPSDIR)/$*.shbin.d
	echo "extern const u8" `(echo $(CURBIN) | tr . _)`"_end[];" > `(echo $(CURBIN) | tr . _)`.h
	echo "extern const u8" `(echo $(CURBIN) | tr . _)`"[];" >> `(echo $(CURBIN) | tr . _)`.h
	echo "extern const u32" `(echo $(CURBIN) | tr . _)`_size";" >> `(echo $(CURBIN) | tr . _)`.h
	picasso -o $(CURBIN) $1
	bin2s $(CURBIN) | $(AS) -o $*.shbin.o
endef

%.shbin.o %_shbin.h : %.v.pica
#---------------------------------------------------------------------------------
	@echo $(notdir $<)
	@$(call shader-as,$< $(filter-out $<,$(filter %.v.pica,$^)))

# geolit.v.pica links into geosolid's shbin, after it: one DVLP for both,
# so citro3d sends no shader code when the race switches between them, and
# picasso gives the uniforms they share the same registers (step 13b-5).
# DVLE 0 is geosolid's, 1 geolit's.
geosolid.shbin.o geosolid_shbin.h : geolit.v.pica

-include $(DEPSDIR)/*.d

#---------------------------------------------------------------------------------------
endif
#---------------------------------------------------------------------------------------
