'''
MIT License

Copyright (c) 2024 VincentNL

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

import os
import math
import io
import struct
import numpy as np
import zlib

class decode:

    def __init__(self, files_lst=None, fmt=None, out_dir=None, args_str=None):
        self.files_lst = files_lst
        self.out_dir = out_dir
        self.fmt = fmt
        self.flip = ""  # Default value for flip
        self.log = False  # Default value for log flag
        self.silent = False  # Default value for silent flag
        self.debug = False  # Default value for debug flag

        if len(files_lst)==0 or files_lst == '':
            print('No file specified!')
            return

        if fmt is None:
            self.fmt = "png"

        if out_dir is None:
            self.out_dir = os.path.abspath(os.path.dirname(files_lst[0]))
        else:
            self.out_dir = out_dir

        # Determine out_dir
        if args_str:
            args = args_str.split()  # Split the string into individual arguments

            # Iterate through the arguments to find flip, log, and debug options
            for arg in args:
                if arg.startswith('-flip'):
                    # If -flip is found, extract the flip value
                    self.flip = arg[len('-flip'):]
                elif arg == '-log':
                    self.log = True
                elif arg == '-dbg':
                    self.debug = True
                elif arg == '-silent':
                    self.silent = True


        self.px_modes = {
            0: 'ARGB1555',
            1: 'RGB565',
            2: 'ARGB4444',
            3: 'YUV422',
            4: 'BUMP',
            5: 'RGB555',
            6: 'YUV420',
            7: 'ARGB8888',
            8: 'PAL-4',
            9: 'PAL-8',
            10: 'AUTO',
        }

        self.tex_modes = {
            1: 'Twiddled',
            2: 'Twiddled + Mips',
            3: 'Twiddled VQ',
            4: 'Twiddled VQ + Mips',
            5: 'Twiddled Pal4 (16-col)',
            6: 'Twiddled Pal4 + Mips (16-col)',
            7: 'Twiddled Pal8 (256-col)',
            8: 'Twiddled Pal8 + Mips (256-col)',
            9: 'Rectangle',
            10: 'Rectangle + Mips',
            11: 'Stride',
            12: 'Stride + Mips',
            13: 'Twiddled Rectangle',
            14: 'BMP',
            15: 'BMP + Mips',
            16: 'Twiddled SmallVQ',
            17: 'Twiddled SmallVQ + Mips',
            18: 'Twiddled Alias + Mips',
        }

        # remove companion .PVP/.PVR, filter the list
        new_list = []
        for item in files_lst:
            key = item[:-4]
            if not any(key == x[:-4] for x in new_list):
                new_list.append(item)
        files_lst = new_list

        selected_files = len(files_lst)
        current_file = 0

        # create Extracted\ACT folders
        if self.debug: print(out_dir + '\ACT')

        # create log file
        if self.log:
            with open(f'{out_dir}/pvr_log.txt', 'w') as l:
                l.write('')

        while current_file < selected_files:
            if not files_lst:  # If no files are selected
                break

            cur_file = files_lst[current_file]
            file_name = os.path.split(cur_file)[1]
            filetype = cur_file[-4:]
            PVR_file = cur_file[:-4] + '.pvr'
            PVP_file = cur_file[:-4] + '.pvp'

            # Check if PVP or PVR file exists
            pvp_exists = os.path.exists(PVP_file)
            pvr_exists = os.path.exists(PVR_file)

            apply_palette = True if (filetype == ".pvp" and pvr_exists) or (
                    filetype == ".pvr" and pvp_exists) else False
            act_buffer = bytearray()
            if pvp_exists:
                self.load_pvp(PVP_file, act_buffer, file_name)

            if pvr_exists:
                self.load_pvr(PVR_file, apply_palette, act_buffer, file_name)

            current_file += 1

    def read_col(self,px_format, color):

        if px_format == 0:  # ARGB1555
            a = ((color >> 15) & 0x1) * 0xff
            r = int(((color >> 10) & 0x1f) * 0xff / 0x1f)
            g = int(((color >> 5) & 0x1f) * 0xff / 0x1f)
            b = int((color & 0x1f) * 0xff / 0x1f)
            return (r, g, b, a)

        elif px_format == 1:  # RGB565
            a = 0xff
            r = int(((color >> 11) & 0x1f) * 0xff / 0x1f)
            g = int(((color >> 5) & 0x3f) * 0xff / 0x3f)
            b = int((color & 0x1f) * 0xff / 0x1f)
            return (r, g, b, a)

        elif px_format == 2:  # ARGB4444
            a = ((color >> 12) & 0xf)*0x11
            r = ((color >> 8) & 0xf)*0x11
            g = ((color >> 4) & 0xf)*0x11
            b = (color & 0xf)*0x11
            return (r, g, b, a)

        elif px_format == 5:  # RGB555
            a = 0xFF
            r = int(((color >> 10) & 0x1f) * 0xff / 0x1f)
            g = int(((color >> 5) & 0x1f) * 0xff / 0x1f)
            b = int((color & 0x1f) * 0xff / 0x1f)
            return (r, g, b, a)

        elif px_format in [7]:  # ARGB8888
            a = (color >> 24) & 0xFF
            r = (color >> 16) & 0xFF
            g = (color >> 8) & 0xFF
            b = color & 0xFF
            return (r, g, b, a)

        elif px_format in [14]:  # RGBA8888
            r = (color >> 24) & 0xFF
            g = (color >> 16) & 0xFF
            b = (color >> 8) & 0xFF
            a = color & 0xFF
            return (r, g, b, a)

        elif px_format == 3:

            # YUV422
            yuv0, yuv1 = color

            y0 = (yuv0 >> 8) & 0xFF
            u = yuv0 & 0xFF
            y1 = (yuv1 >> 8) & 0xFF
            v = yuv1 & 0xFF

            # Perform YUV to RGB conversion
            c0 = y0 - 16
            c1 = y1 - 16
            d = u - 128
            e = v - 128

            r0 = max(0, min(255, int((298 * c0 + 409 * e + 128) >> 8)))
            g0 = max(0, min(255, int((298 * c0 - 100 * d - 208 * e + 128) >> 8)))
            b0 = max(0, min(255, int((298 * c0 + 516 * d + 128) >> 8)))

            r1 = max(0, min(255, int((298 * c1 + 409 * e + 128) >> 8)))
            g1 = max(0, min(255, int((298 * c1 - 100 * d - 208 * e + 128) >> 8)))
            b1 = max(0, min(255, int((298 * c1 + 516 * d + 128) >> 8)))

            return r0, g0, b0, r1, g1, b1

    def read_pal(self,mode, color, act_buffer):

        if mode == 4444:
            red = ((color >> 8) & 0xf) << 4
            green = ((color >> 4) & 0xf) << 4
            blue = (color & 0xf) << 4
            alpha = '-'

        if mode == 555:
            red = ((color >> 10) & 0x1f) << 3
            green = ((color >> 5) & 0x1f) << 3
            blue = (color & 0x1f) << 3
            alpha = '-'

        elif mode == 565:
            red = ((color >> 11) & 0x1f) << 3
            green = ((color >> 5) & 0x3f) << 2
            blue = (color & 0x1f) << 3
            alpha = '-'

        elif mode == 8888:
            blue = (color >> 0) & 0xFF
            green = (color >> 8) & 0xFF
            red = (color >> 16) & 0xFF
            alpha = (color >> 24) & 0xFF

        act_buffer += bytes([red, green, blue])
        return act_buffer

    def read_pvp(self,f, act_buffer):

        f.seek(0x08)
        pixel_type = int.from_bytes(f.read(1), 'little')
        if pixel_type == 1:
            mode = 565
        elif pixel_type == 2:
            mode = 4444
        elif pixel_type == 6:
            mode = 8888
        else:
            mode = 555

        f.seek(0x0e)
        ttl_entries = int.from_bytes(f.read(2), 'little')

        f.seek(0x10)  # Start palette data
        current_offset = 0x10

        for counter in range(0, ttl_entries):
            if mode != 8888:
                color = int.from_bytes(f.read(2), 'little')
                act_buffer = self.read_pal(mode, color, act_buffer)
                current_offset += 0x2
            else:
                color = int.from_bytes(f.read(4), 'little')
                act_buffer = self.read_pal(mode, color, act_buffer)
                current_offset += 0x4

        return act_buffer, mode, ttl_entries

    def image_flip(self, data, w, h,cmode):

        if cmode == 'RGB':
            pixels_len = 3
        elif cmode == 'RGBA':
            pixels_len = 4
        else:
            pixels_len = 1

        if self.flip and'v' in self.flip:
            data = (np.flipud((np.array(data)).reshape(h, w, -1)).flatten()).reshape(-1, pixels_len).tolist()

        if self.flip and 'h' in self.flip:
            data = (np.fliplr((np.array(data)).reshape(h, w, -1)).flatten()).reshape(-1, pixels_len).tolist()

        return data

    def save_image(self,file_name,data,bits,w,h,cmode,palette):

        if not os.path.exists(self.out_dir):
            os.makedirs(self.out_dir)

        if self.fmt == 'png':
            self.save_png(file_name,data,bits,w,h,cmode,palette)
        elif self.fmt == 'bmp':
            self.save_bmp(file_name,data,bits,w,h,cmode,palette )
        elif self.fmt == 'tga':
            self.save_tga(file_name,data,bits,w,h,cmode,palette )

        if not self.silent:print(fr"{self.out_dir}\{file_name[:-4]}.{self.fmt}")

    # Incomplete! Not supporting palettized images!
    def save_tga(self, file_name,data,bits,w,h,cmode,palette=None):
        # Define TGA header
        tga_header = bytearray([0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, w & 255, (w >> 8) & 255,
                                h & 255, (h >> 8) & 255, 32, 0])

        # TGA is not reversed by default
        pixel_data = bytearray()

        # Iterate over the flattened array and append the pixel data
        for pixel in data:
            # Assuming pixel is in BGRA format
            pixel_data.extend([pixel[2], pixel[1], pixel[0], pixel[3]])

        # Combine the header and pixel data
        tga_data = tga_header + pixel_data

        # Save the TGA file
        with open(fr'{self.out_dir}\{file_name[:-4]}.tga', "wb") as tga_file:
            tga_file.write(tga_data)


    def save_bmp(self, file_name, data, bits, w, h, cmode, palette=None):
        # Define BMP file header
        file_header = bytearray([66, 77, 54, 0, 0, 0, 0, 0, 0, 0, 54, 0, 0, 0]) # BMP string
        pixel_data = bytearray()

        # Define DIB header
        if cmode == 'RGB':
            bpp_var = 24
        elif cmode == 'RGBA':
            bpp_var = 32
        else:
            bpp_var = bits

        #print(len(palette))
        if 'PAL' in cmode:
            # Add palette to DIB header
            palette_data = bytearray()
            for color in palette:
                palette_data.extend([color[2], color[1], color[0], 0])  # Assuming RGB format, add padding
        else:
            palette_data = bytes()
            palette = bytes(0)

        dib_header = bytearray([40, 0, 0, 0,  # DIB header size
                                w & 255, (w >> 8) & 255, (w >> 16) & 255, (w >> 24) & 255,  # Image width
                                h & 255, (h >> 8) & 255, (h >> 16) & 255, (h >> 24) & 255,  # Image height
                                1, 0,  # Color planes
                                bpp_var, 0,  # Bits per pixel
                                0, 0, 0, 0,  # Compression method (0 for uncompressed)
                                0, 0, 0, 0,  # Image size (0 for uncompressed)
                                0, 0, 0, 0,  # Horizontal resolution (pixels per meter)
                                0, 0, 0, 0,  # Vertical resolution (pixels per meter)
                                len(palette) & 255, (len(palette) >> 8) & 255, 0, 0,  # Number of colors in the palette
                                0, 0, 0, 0])  # Number of important colors


        # Combine the header and DIB header
        header = file_header + dib_header + palette_data

        if 'PAL' in cmode:
            data = [item for sublist in data for item in sublist]
            # Calculate the length of each index sublist

            if cmode == 'RGB-PAL16':
                sublist_length = w//2
            else:
                sublist_length = w  #'RGB-PAL256'

            sublists = [data[i:i + sublist_length] for i in range(0, len(data), sublist_length)]
            reversed_sublists = sublists[::-1]
            pixel_data = bytes([item for sublist in reversed_sublists for item in sublist])

        else:
            # Bmp default order is left-right, bottom-top
            for y in range(h - 1, -1, -1):
                for x in range(w):
                    # Assuming pixel is in BGRA format
                    pixel = data[y * w + x]
                    if cmode == 'RGBA':
                        pixel_data.extend([pixel[2], pixel[1], pixel[0], pixel[3]])
                    elif cmode == 'RGB':
                        pixel_data.extend([pixel[2], pixel[1], pixel[0]])

        # Combine the header, palette (if any), and pixel data
        bmp_data = header + pixel_data

        # Save the BMP file
        with open(fr'{self.out_dir}\{file_name[:-4]}.bmp', "wb") as bmp_file:
            bmp_file.write(bmp_data)


    def save_png(self, file_name,data, bits, w, h, cmode, palette):

        Pixel = None
        #print(cmode)

        if cmode == 'RGB':
            Pixel = tuple[int, int, int]

        elif cmode == 'RGBA':
            Pixel = tuple[int, int, int, int]


        image_data = list[list[Pixel]]

        def encode_data(image_data: list[list[Pixel]]) -> list[int]:
            ret = []

            for row in image_data:
                ret.extend([0] + [pixel for color in row for pixel in color])

            return ret

        def calculate_checksum(chunk_type: bytes, data: bytes) -> int:
            checksum = zlib.crc32(chunk_type)
            checksum = zlib.crc32(data, checksum)
            return checksum

        def palette_to_bytearray(palette):
            # Ensure each RGB tuple has three components
            palette = [tuple(rgb[:3]) for rgb in palette]

            # Flatten the RGB tuples and pack them into a bytearray
            byte_array = bytearray()
            for rgb in palette:
                byte_array.extend(struct.pack('BBB', *rgb))
            return byte_array

        color_type = 2  # truecolor by default

        if cmode == 'RGB':
            color_type = 2  # truecolor
        elif cmode == 'RGBA':
            color_type = 6  # truecolor with alpha
        elif 'PAL' in cmode:
            color_type = 3  # indexed color

            # Convert palette to a bytearray
            bytearray_palette = palette_to_bytearray(palette)

        if 'PAL' in cmode:
            # Create indexes
            indexes = [item for sublist in data for item in sublist]
            image_bytes = bytearray([0] + indexes)  # Filter type 0 for the first scanline

            png_array = []

            if cmode == 'RGB-PAL16':
                row_lenght = (w // 2)
            else:
                row_lenght = (w)

            for y in range(h):
                png_array.append(0)  # Filter type 0 for each scanline
                for x in range(row_lenght):
                    png_array.append(x + y * row_lenght + 1)

            # Rearrange indexes based on png_array order
            image_data = bytearray([image_bytes[i] for i in png_array])

        else:
            # Arrange image data into rows
            image_data= bytearray(encode_data([data[i:i + w] for i in range(0, len(data), w)]))


        # Compress image data using zlib with compression level 0
        compressed_data = zlib.compress(image_data,level=1)

        # Write PNG signature
        signature = b'\x89PNG\r\n\x1a\n'

        with open(fr'{self.out_dir}\{file_name[:-4]}.png', "wb") as out:
            out.write(signature)

            # Write IHDR chunk
            ihdr_chunk = struct.pack('!I', w) + struct.pack('!I', h) + bytes([bits, color_type, 0, 0, 0])
            checksum = calculate_checksum(b'IHDR', ihdr_chunk)
            out.write(struct.pack('!I', len(ihdr_chunk)) + b'IHDR' + ihdr_chunk + struct.pack('!I', checksum))

            if 'PAL' in cmode:
                # Write PLTE chunk
                checksum = calculate_checksum(b'PLTE', bytearray_palette)
                out.write(
                    struct.pack('!I', len(bytearray_palette)) + b'PLTE' + bytearray_palette + struct.pack('!I',
                                                                                                          checksum))

            # Write IDAT chunk (compressed image data)
            checksum = calculate_checksum(b'IDAT', compressed_data)
            # print(struct.pack('!I', len(compressed_data)))
            out.write(
                struct.pack('!I', len(compressed_data)) + b'IDAT' + compressed_data + struct.pack('!I', checksum))

            # Write IEND chunk
            checksum = calculate_checksum(b'IEND', b'')
            out.write(struct.pack('!I', 0) + b'IEND' + struct.pack('!I', checksum))

    def write_act(self,act_buffer, file_name):
        #print(act_buffer)

        if not os.path.exists(self.out_dir + '\ACT'):
            os.makedirs(self.out_dir + '\ACT')

        with open((fr"{self.out_dir}\ACT/{file_name[:-4]}.ACT"), 'w+b') as n:

            # Pad file with 0x00 if 16-color palette

            if len(act_buffer) < 768:
                act_file = bytes(act_buffer) + bytes(b'\x00' * (768 - len(act_buffer)))
            else:
                act_file = bytes(act_buffer)
            n.write(act_file)

    def detwiddle(self,w, h):
        # Initialize variables
        index = 0
        pat2, h_inc, arr, h_arr = [], [], [], []

        # Build Twiddle index table
        seq = [2, 6, 2, 22, 2, 6, 2]
        pat = seq + [86] + seq + [342] + seq + [86] + seq

        for i in range(4):
            pat2 += [1366, 5462, 1366, 21846]
            pat2 += [1366, 5462, 1366, 87382] if i % 2 == 0 else [1366, 5462, 1366, 349526]

        for i in range(len(pat2)):
            h_inc.extend(pat + [pat2[i]])
        h_inc.extend(pat)

        # Rectangle (horizontal)
        if w > h:
            ratio = int(w / h)

            # print(f'width is {ratio} times height!')

            if w % 32 == 0 and w & (w - 1) != 0 or h & (h - 1) != 0:
                # print('h and w not power of 2. Using Stride format')
                n = h * w
                for i in range(n):
                    arr.append(i)
            else:
                # Single block h_inc length
                cur_h_inc = {w: h_inc[0:h - 1] + [2]}  # use height size to define repeating block h_inc

                # define the first horizontal row of image pixel array:
                for j in range(ratio):
                    if w in cur_h_inc:
                        for i in cur_h_inc[w]:
                            h_arr.append(index)
                            index += i
                    index = (len(h_arr) * h)

                # define the vertical row of image pixel array of repeating block:
                v_arr = [int(x / 2) for x in h_arr]
                v_arr = v_arr[0:h]

                for val in v_arr:
                    arr.extend([x + val for x in h_arr])

        # Rectangle (vertical)
        elif h > w:
            ratio = int(h / w)
            # print(f'height is {ratio} times width!')

            # Set the size of pixel increase array
            cur_h_inc = {w: h_inc[0:w - 1] + [2]}

            # define the first horizontal row of image pixel array:
            if w in cur_h_inc:
                for i in cur_h_inc[w]:
                    h_arr.append(index)
                    index += i

            # define the vertical row of image pixel array:
            v_arr = [int(x / 2) for x in h_arr]

            # Repeat vertical array block from the last value of array * h/w ratio
            for i in range(ratio):
                if i == 0:
                    last_val = 0
                else:
                    last_val = arr[-1] + 1

                for val in v_arr:
                    arr.extend([last_val + x + val for x in h_arr])

        elif w == h:  # Square
            cur_h_inc = {w: h_inc[0:w - 1] + [2]}
            # define the first horizontal row of image pixel array:
            if w in cur_h_inc:
                for i in cur_h_inc[w]:
                    h_arr.append(index)
                    index += i

            # define the vertical row of image pixel array:
            v_arr = [int(x / 2) for x in h_arr]

            for val in v_arr:
                arr.extend([x + val for x in h_arr])

        return arr

    def decode_pvr(self, f, file_name, w, h, offset=None, px_format=None, tex_format=None, apply_palette=None,
                   act_buffer=None):
        f.seek(offset)
        data = bytearray()

        if tex_format not in [9, 10, 11, 12, 14, 15]:
            arr = self.detwiddle(w, h)

        if tex_format in [5, 6, 7, 8]:

            cmode = None
            if tex_format in [7, 8]:  # 8bpp
                palette_entries = 256
                bits = 8
                pixels = list(f.read(w * h))
                data = [pixels[i] for i in arr]

                if self.flip != '':
                    data = self.image_flip(data, w, h, cmode)
                    # Flatten the nested list and convert each value to an integer
                    data = [int(value) for sublist in data for value in sublist]

                # 4bpp, convert to 8bpp
            else:
                palette_entries = 16
                bits = 4
                pixels = bytearray(f.read(w * h // 2))  # read only required amount of bytes

                # Read 4bpp to 8bpp indexes
                data = []
                for i in range(len(pixels)):
                    data.append(((pixels[i]) & 0x0f) * 0x11)  # last 4 bits
                    data.append((((pixels[i]) & 0xf0) >> 4) * 0x11)  # first 4 bits

                # Assuming 'data' contains the 8bpp indexes
                new_pixels = bytearray(data)

                # Detwiddle 8bpp indexes
                data = []
                for num in arr:
                    data.append(new_pixels[num])

                if self.flip != '':
                    data = self.image_flip(data, w, h, cmode)

                    # Flatten the nested list and convert each value to an integer
                    data = [int(value) for sublist in data for value in sublist]

                data = bytearray(data)  # 8bpp "twiddled data" back into "pixels" variable
                # Convert back to 4bpp indexes with swapped upper and lower bits

                converted_data = bytearray()
                for i in range(0, len(data), 2):

                    # Swap the position of upper and lower bits
                    index1 = (data[i] // 0x11) << 4 | (data[i + 1] // 0x11)

                    # Append the modified index to the converted data
                    converted_data.append(index1)

                data = converted_data

            data = [data]

            if palette_entries == 16:
                if apply_palette == True:
                    palette = [tuple(act_buffer[i:i + 3]) for i in range(0, len(act_buffer), 3)]

                else:palette = [(i * 17, i * 17, i * 17) for i in range(16)]
                cmode = 'RGB-PAL16'

            elif palette_entries == 256:
                if apply_palette == True:
                    palette = [tuple(act_buffer[i:i + 3]) for i in range(0, len(act_buffer), 3)]


                else:palette = [(i, i, i) for i in range(256)]
                cmode = 'RGB-PAL256'

            self.save_image(file_name, data, bits, w, h, cmode, palette)

        # VQ
        elif tex_format in [3, 4, 16, 17]:

            codebook_size = 256

            # SmallVQ - Thanks Kion! :)

            if tex_format == 16:
                if w <= 16:
                    codebook_size = 16
                elif w == 32:
                    codebook_size = 32
                elif w == 64:
                    codebook_size = 128
                else:
                    codebook_size = 256

            # SmallVQ + Mips
            elif tex_format == 17:
                if w <= 16:
                    codebook_size = 16
                elif w == 32:
                    codebook_size = 64
                else:
                    codebook_size = 256

            # print(codebook_size)

            codebook = []

            if px_format not in [3]:
                cmode = 'RGBA'
                for l in range(codebook_size):
                    block = []
                    for i in range(4):
                        pixel = (int.from_bytes(f.read(2), 'little'))
                        pix_col = self.read_col(px_format, pixel)
                        block.append(pix_col)

                    codebook.append(block)

            # YUV422

            else:
                cmode = 'RGB'
                yuv_codebook = []
                for l in range(codebook_size):
                    block = []
                    for i in range(4):
                        pixel = (int.from_bytes(f.read(2), 'little'))
                        block.append(pixel)

                    r0, g0, b0, r1, g1, b1 = self.read_col(px_format, (block[0], block[3]))
                    r2, g2, b2, r3, g3, b3 = self.read_col(px_format, (block[1], block[2]))

                    yuv_codebook.append([(r0, g0, b0), (r2, g2, b2), (r3, g3, b3), (r1, g1, b1)])

                codebook = yuv_codebook

            # VQ Mips!
            if tex_format in [4, 17]:

                pvr_dim = [4, 8, 16, 32, 64, 128, 256, 512, 1024]
                mip_size = [0x10, 0x40, 0x100, 0x400, 0x1000, 0x4000, 0x10000, 0x40000]
                size_adjust = {4: 1, 17: 1}  # 8bpp size is 4bpp *2
                extra_mip = {4: 0x6, 17: 0x6, }  # smallest mips fixed size

                for i in range(len(pvr_dim)):
                    if pvr_dim[i] == w:
                        mip_index = i - 1
                        break

                # Skip mips for image data offset
                mip_sum = (sum(mip_size[:mip_index]) * size_adjust[tex_format]) + (extra_mip[tex_format])

                f.seek(f.tell() + mip_sum)
                # print(hex(f.tell()))

            # Read pixel_index:
            pixel_list = []
            bytes_to_read = int((w * h) / 4)

            # Each index stores 4 pixels
            for i in range(bytes_to_read):
                pixel_index = (int.from_bytes(f.read(1), 'little'))
                pixel_list.append(int(pixel_index))

            # Detwiddle image data indices, put them into arr list
            arr = self.detwiddle(int(w / 2), int(h / 2))

            # Create an empty 2D array to store pixel data
            image_array = [[(0, 0, 0, 0) for _ in range(w)] for _ in range(h)]

            # Iterate over the blocks and update the pixel values in the array
            i = 0
            for y in range(h//2):
                for x in range(w//2):
                    image_array[y * 2][x * 2] = codebook[pixel_list[arr[i]]][0]
                    image_array[y * 2 + 1][x * 2] = codebook[pixel_list[arr[i]]][1]
                    image_array[y * 2][x * 2 + 1] = codebook[pixel_list[arr[i]]][2]
                    image_array[y * 2 + 1][x * 2 + 1] = codebook[pixel_list[arr[i]]][3]
                    i += 1

            # Flatten the 2D array to a 1D list for putdata
            data = [pixel for row in image_array for pixel in row]
            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            palette = ''
            # save the image
            self.save_image(file_name,data,8,w,h,cmode,palette)

        # BMP ABGR8888
        elif tex_format in [14, 15]:
            pixels = [int.from_bytes(f.read(4), 'little') for _ in range(w * h)]
            data = [(self.read_col(14, p)) for p in pixels]

            palette = ''
            cmode = 'RGBA'

            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            # save the image
            self.save_image(file_name,data,8,w,h,cmode,palette)

        # BUMP loop
        elif px_format == 4:
            pixels = [int.from_bytes(f.read(2), 'little') for _ in range(w * h)]
            data = [self.cart_to_rgb(self.process_SR(p)) for p in (pixels[i] for i in arr)]

            palette = ''
            cmode = 'RGB'

            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            # save the image
            self.save_image(file_name,data,8,w,h,cmode,palette)

        # ARGB modes
        elif px_format in [0, 1, 2, 5, 7, 18]:

            pixels = [int.from_bytes(f.read(2), 'little') for _ in range(w * h)]

            if tex_format not in [9, 10, 11, 12, 14, 15]:  # If Twiddled
                data = [(self.read_col(px_format, p)) for p in (pixels[i] for i in arr)]
            else:
                data = [(self.read_col(px_format, p)) for p in pixels]

            palette = ''
            cmode = 'RGBA'

            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            # save the image
            self.save_image(file_name,data,8,w,h,cmode,palette)

        # YUV420 modes
        elif px_format in [6]:
            data = []
            self.yuv420_to_rgb(f, w, h, data)

            palette = ''
            cmode = 'RGB'

            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            # save the image
            self.save_image(file_name, data, 8,w, h, cmode, palette)


        # YUV422 modes
        elif px_format in [3]:
            data = []

            # Twiddled
            if tex_format not in [9, 10, 11, 12, 14, 15]:
                i = 0
                offset = f.tell()

                for y in range(h):
                    for x in range(0, w, 2):
                        f.seek(offset + (arr[i] * 2))
                        yuv0 = int.from_bytes(f.read(2), 'little')
                        i += 1
                        f.seek(offset + (arr[i] * 2))
                        yuv1 = int.from_bytes(f.read(2), 'little')
                        r0, g0, b0, r1, g1, b1 = self.read_col(px_format, (yuv0, yuv1))
                        data.append((r0, g0, b0))
                        data.append((r1, g1, b1))
                        i += 1



            else:
                for y in range(h):
                    for x in range(0, w, 2):
                        # Read yuv0 and yuv1 separately
                        yuv0 = int.from_bytes(f.read(2), 'little')
                        yuv1 = int.from_bytes(f.read(2), 'little')
                        r0, g0, b0, r1, g1, b1 = self.read_col(px_format, (yuv0, yuv1))
                        data.append((r0, g0, b0))
                        data.append((r1, g1, b1))


            palette = ''
            cmode = 'RGB'

            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            # save the image
            self.save_image(file_name,data,8,w,h,cmode,palette)

    def load_pvr(self, PVR_file, apply_palette, act_buffer, file_name):
        px_modes = self.px_modes
        tex_modes = self.tex_modes

        with open(PVR_file, 'rb') as f:
            # Wrap file content in a BytesIO object
            f_buffer = io.BytesIO(f.read())

            header_data = f_buffer.getvalue()
            gbix_offset = header_data.find(b"GBIX")

            if gbix_offset != -1:
                f_buffer.seek(gbix_offset + 0x4)
                gbix_size = int.from_bytes(f_buffer.read(4), byteorder='little')
                if gbix_size == 0x8:
                    gbix_val1 = int.from_bytes(f_buffer.read(4), byteorder='little')
                    gbix_val2 = int.from_bytes(f_buffer.read(4), byteorder='little')
                    if self.debug:
                        print(hex(gbix_val1), hex(gbix_val2))
                elif gbix_size == 0x4:
                    gbix_val1 = int.from_bytes(f_buffer.read(4), byteorder='little')
                    gbix_val2 = ''
                else:
                    print('invalid or unsupported GBIX size:', gbix_size, file_name)
            else:
                if self.debug:
                    print('GBIX found at:', hex(gbix_offset))
                gbix_val1 = ''
                gbix_val2 = ''

            offset = header_data.find(b"PVRT")
            if offset != -1 or len(header_data) < 0x10:
                f_buffer.seek(offset + 0x8)

                # Pixel format
                px_format = int.from_bytes(f_buffer.read(1), byteorder='little')
                tex_format = int.from_bytes(f_buffer.read(1), byteorder='little')

                f_buffer.seek(f_buffer.tell() + 2)

                # Image size
                w = int.from_bytes(f_buffer.read(2), byteorder='little')
                h = int.from_bytes(f_buffer.read(2), byteorder='little')
                offset = f_buffer.tell()

                if self.debug:
                    print(PVR_file.split('/')[-1], 'size:', w, 'x', h, 'format:',
                          f'[{tex_format}] {tex_modes[tex_format]}', f'[{px_format}] {px_modes[px_format]}')

                if tex_format in [2, 4, 6, 8, 10, 12, 15, 17, 18]:
                    if tex_format in [2, 6, 8, 10, 15, 18]:
                        # Mips skip
                        pvr_dim = [4, 8, 16, 32, 64, 128, 256, 512, 1024]
                        mip_size = [0x20, 0x80, 0x200, 0x800, 0x2000, 0x8000, 0x20000, 0x80000]
                        size_adjust = {2: 4, 6: 1, 8: 2, 10: 4, 15: 8, 18: 4}  # 8bpp size is 4bpp *2
                        extra_mip = {2: 0x2c, 6: 0xc, 8: 0x18, 10: 0x2c, 15: 0x54,
                                     18: 0x30}  # smallest mips fixed size

                        for i in range(len(pvr_dim)):
                            if pvr_dim[i] == w:
                                mip_index = i - 1
                                break

                        mip_sum = (sum(mip_size[:mip_index]) * size_adjust[tex_format]) + (extra_mip[tex_format])

                        offset += mip_sum

                self.decode_pvr(f_buffer, file_name, w, h, offset, px_format, tex_format, apply_palette, act_buffer)

                if self.log:
                    log_content = (
                        f"Filename: {PVR_file}, size: {w}x{h}, format: {tex_modes[tex_format]}, "
                        f"mode: {px_modes[px_format]}"
                        f"{f', GBIX: {gbix_val1}' if gbix_val1 != '' else ', GBIX1: ---'}"
                        f"{f', GBIX2: {gbix_val2}' if gbix_val2 != '' else ', GBIX2: ---'}\n"
                    )

                    with open(f'{self.out_dir}/pvr_log.txt', 'a') as l:
                        l.write(log_content)
            else:
                print("'PVRT' header not found!")

    def load_pvp(self,PVP_file, act_buffer, file_name):
        try:
            with open(PVP_file, 'rb') as f:
                file_size = len(f.read())
                f.seek(0x0)
                PVP_check = f.read(4)

                if PVP_check == b'PVPL' and file_size > 0x10:  # PVPL header and size are OK!
                    act_buffer, mode, ttl_entries = self.read_pvp(f, act_buffer)
                    self.write_act(act_buffer, file_name)

                else:
                    print('Invalid .PVP file!')  # Skip this file
        except:
            print(f'PVP data error! {PVP_file}')
        return act_buffer

    def process_SR(self,SR_value):
        S = (1.0 - ((SR_value >> 8) / 255.0)) * math.pi / 2
        R = (SR_value & 0xFF) / 255.0 * 2 * math.pi - 2 * math.pi * (SR_value & 0xFF > math.pi)
        red = (math.sin(S) * math.cos(R) + 1.0) * 0.5
        green = (math.sin(S) * math.sin(R) + 1.0) * 0.5
        blue = (math.cos(S) + 1.0) * 0.5
        return red, green, blue

    def cart_to_rgb(self,cval):
        return tuple(int(c * 255) for c in cval)

    def yuv420_to_rgb(self,f, w, h, data):
        # Credits to Egregiousguy for YUV420 --> YUV420P conversion
        buffer = bytearray()

        col = w // 16
        row = h // 16

        U = [bytearray() for _ in range(8 * row)]
        V = [bytearray() for _ in range(8 * row)]
        Y01 = [bytearray() for _ in range(col)]
        Y23 = [bytearray() for _ in range(col)]

        for i in range(1, row + 1):
            for n in range(8):
                U[n + 8 * (i - 1)] = bytearray()

            for n in range(col):
                Y01[n] = bytearray()
                Y23[n] = bytearray()

            for _ in range(col):
                for n in range(8):
                    U[n + 8 * (i - 1)] += f.read(0x8)

                for n in range(8):
                    V[n + 8 * (i - 1)] += f.read(0x8)

                for _ in range(2):
                    for n in range(8):
                        Y01[n] += f.read(0x8)

                for _ in range(2):
                    for n in range(8):
                        Y23[n] += f.read(0x8)

            for n in range(col):
                buffer += Y01[n]

            for n in range(col):
                buffer += Y23[n]

        for datauv in U + V:
            buffer += datauv

        # Extract Y, U, and V components from the buffer
        Y = list(buffer[:int(w * h)])
        U = list(buffer[int(w * h):int(w * h * 1.25)])
        V = list(buffer[int(w * h * 1.25):])

        # Reshape Y, U, and V components
        Y = [Y[i:i + w] for i in range(0, len(Y), w)]
        U = [U[i:i + w // 2] for i in range(0, len(U), w // 2)]
        V = [V[i:i + w // 2] for i in range(0, len(V), w // 2)]

        # Upsample U and V components
        U = [item for sublist in U for item in [item for item in sublist] * 2]
        V = [item for sublist in V for item in [item for item in sublist] * 2]

        # Reshape U and V components after upsampling
        U = [U[i:i + w] for i in range(0, len(U), w)]
        V = [V[i:i + w] for i in range(0, len(V), w)]

        # Convert YUV to RGB
        for i in range(h):
            for j in range(w):
                i_UV = min(i // 2, len(U) - 1)
                j_UV = min(j // 2, len(U[i_UV]) - 1)
                y, u, v = Y[i][j], U[i_UV][j_UV], V[i_UV][j_UV]
                r = int(max(0, min(255, round(y + 1.402 * (v - 128)))))
                g = int(max(0, min(255, round(y - 0.344136 * (u - 128) - 0.714136 * (v - 128)))))
                b = int(max(0, min(255, round(y + 1.772 * (u - 128)))))
                data.append((r, g, b))
        return data
