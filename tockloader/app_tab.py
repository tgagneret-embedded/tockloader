import struct
import textwrap

class TabApp:
	'''
	Representation of a Tock app for a specific board from a TAB file. This is
	different from a TAB, since a TAB can include compiled binaries for a range
	of architectures, or compiled for various scenarios, which may not be
	applicable for a particular board.

	A TabApp need not be a single (TBF header, binary) pair, as an app from a
	TAB can include multiple (header, binary) pairs if the app was compiled
	multiple times. This could be for any reason (e.g. it was signed with
	different keys, or it uses different compiler optimizations), but typically
	this is because it is compiled for specific addresses in flash and RAM, and
	there are multiple linked versions present in the TAB. If so, there will be
	multiple (header, binary) pairs included in this App object, and the correct
	one for the board will be used later.
	'''

	def __init__ (self, tbfs):
		'''
		Create a `TabApp` from a list of (TBF header, app binary) pairs.
		'''
		self.tbfs = tbfs # A list of (TBF header, app binary) pairs.

	def get_name (self):
		'''
		Return the app name.
		'''
		app_names = set([tbf[0].get_app_name() for tbf in self.tbfs])
		if len(app_names) > 1:
			raise TockLoaderException('Different names inside the same TAB?')
		elif len(app_names) == 0:
			raise TockLoaderException('No name in the TBF binaries')

		return app_names.pop()

	def is_modified (self):
		'''
		Returns whether this app needs to be flashed on to the board. Since this
		is a TabApp, we did not get this app from the board and therefore we
		have to flash this to the board.
		'''
		return True

	def set_sticky (self):
		'''
		Mark this app as "sticky" in the app's header. This makes it harder to
		accidentally remove this app if it is a core service or debug app.
		'''
		for tbfh,binary in self.tbfs:
			tbfh.set_flag('sticky', True)

	def get_size (self):
		'''
		Return the total size (including TBF header) of this app in bytes.
		'''
		app_sizes = set([tbf[0].get_app_size() for tbf in self.tbfs])
		if len(app_sizes) > 1:
			raise TockLoaderException('Different app sizes inside the same TAB?')
		elif len(app_sizes) == 0:
			raise TockLoaderException('No TBF apps')

		return app_sizes.pop()

	def get_header (self):
		'''
		Return a header if there is only one.
		'''
		if len(self.tbfs) == 1:
			return self.tbfs[0][0]
		return None

	def set_size (self, size):
		'''
		Force the entire app to be a certain size. If `size` is smaller than the
		actual app an error will be thrown.
		'''
		for tbfh,app_binary in self.tbfs:
			header_size = tbfh.get_header_size()
			binary_size = len(app_binary)
			current_size = header_size + binary_size
			if size < current_size:
				raise TockLoaderException('Cannot make app smaller. Current size: {} bytes'.format(current_size))
			tbfh.set_app_size(size)

	def has_fixed_addresses(self):
		'''
		Return true if any TBF binary in this app is compiled for a fixed
		address. That likely implies _all_ binaries are compiled for a fixed
		address.
		'''
		has_fixed_addresses = False
		for tbfh,app_binary in self.tbfs:
			if tbfh.has_fixed_addresses():
				has_fixed_addresses = True
				break
		return has_fixed_addresses

	def has_app_binary (self):
		'''
		Return true if we have an application binary with this app.
		'''
		# By definition, a TabApp will have an app binary.
		return True

	def get_binary (self, address):
		'''
		Return the binary array comprising the entire application.

		`address` is the address of flash the _start_ of the app will be placed
		at. This means where the TBF header will go.
		'''
		# See if there is binary that we have that matches the address
		# requirement.
		binary = None
		for tbfh,app_binary in self.tbfs:
			# If the TBF is not compiled for a fixed address, then we can just
			# use it.
			if tbfh.has_fixed_addresses() == False:
				binary = tbfh.get_binary() + app_binary
				break

			else:
				# Check the fixed address, and see if the TBF header ends up at
				# the correct address.
				fixed_flash_address = tbfh.get_fixed_addresses()[0]
				tbf_header_length = tbfh.get_header_size()

				if fixed_flash_address - tbf_header_length == address:
					binary = tbfh.get_binary() + app_binary
					break

		# We didn't find a matching binary.
		if binary == None:
			return None

		# Check that the binary is not longer than it is supposed to be. This
		# might happen if the size was changed, but any code using this binary
		# has no way to check. If the binary is too long, we truncate the actual
		# binary blob (which should just be padding) to the correct length. If
		# it is too short it is ok, since the board shouldn't care what is in
		# the flash memory the app is not using.
		size = self.get_size()
		if len(binary) > size:
			binary = binary[0:size]

		return binary

	def get_crt0_header_str (self):
		'''
		Return a string representation of the crt0 header some apps use for
		doing PIC fixups. We assume this header is positioned immediately
		after the TBF header.
		'''
		tbfh,app_binary = self.tbfs[0]
		header_size = tbfh.get_header_size()
		app_binary_notbfh = app_binary

		crt0 = struct.unpack('<IIIIIIIIII', app_binary_notbfh[0:40])

		out = ''
		out += '{:<20}: {:>10} {:>#12x}\n'.format('got_sym_start', crt0[0], crt0[0])
		out += '{:<20}: {:>10} {:>#12x}\n'.format('got_start', crt0[1], crt0[1])
		out += '{:<20}: {:>10} {:>#12x}\n'.format('got_size', crt0[2], crt0[2])
		out += '{:<20}: {:>10} {:>#12x}\n'.format('data_sym_start', crt0[3], crt0[3])
		out += '{:<20}: {:>10} {:>#12x}\n'.format('data_start', crt0[4], crt0[4])
		out += '{:<20}: {:>10} {:>#12x}\n'.format('data_size', crt0[5], crt0[5])
		out += '{:<20}: {:>10} {:>#12x}\n'.format('bss_start', crt0[6], crt0[6])
		out += '{:<20}: {:>10} {:>#12x}\n'.format('bss_size', crt0[7], crt0[7])
		out += '{:<20}: {:>10} {:>#12x}\n'.format('reldata_start', crt0[8], crt0[8])
		out += '{:<20}: {:>10} {:>#12x}\n'.format('stack_size', crt0[9], crt0[9])

		return out

	# def info (self, verbose=False):
	# 	'''
	# 	Get a string describing various properties of the app.
	# 	'''
	# 	out = ''
	# 	for tbfh,app_binary in self.tbfs:
	# 		out += 'Name:                  {}\n'.format(self.get_name())
	# 		out += 'Enabled:               {}\n'.format(tbfh.is_enabled())
	# 		out += 'Sticky:                {}\n'.format(tbfh.is_sticky())
	# 		out += 'Total Size in Flash:   {} bytes\n'.format(self.get_size())

	# 		if verbose:
	# 			out += textwrap.indent(str(tbfh), '  ')
	# 	return out

	def __str__ (self):
		return self.get_name()